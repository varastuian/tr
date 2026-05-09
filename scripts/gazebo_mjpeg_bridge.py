#!/usr/bin/env python3
"""
Bridge Gazebo / gz camera RTP-over-UDP (e.g. port 5600) to MJPEG-over-HTTP for the Next.js map overlay.

Uses GStreamer (same stack as gz camera + gst-launch). Browsers still need HTTP, so we serve multipart MJPEG.

  python3 scripts/gazebo_mjpeg_bridge.py

Typical deps (Ubuntu/Debian):
  sudo apt install python3-gi gstreamer1.0-plugins-base gstreamer1.0-plugins-good \\
    gstreamer1.0-plugins-bad gstreamer1.0-libav

Frontend: set Gazebo stream URL to http://127.0.0.1:8080/stream

If your gz stream uses non-default RTP caps, pass --rtp-caps (must match gst-launch udpsrc caps).
"""

from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse


try:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
except ImportError as e:  # pragma: no cover
    sys.stderr.write(
        "Missing GStreamer Python bindings. Install python3-gi and GStreamer plugins (see script docstring).\n"
        f"Original error: {e}\n"
    )
    raise SystemExit(1) from e

Gst.init(None)

_BOUNDARY_STR = "FRAME"


def _boundary_header() -> bytes:
    # multipart/x-mixed-replace framing
    return f"--{_BOUNDARY_STR}\r\n".encode()


def _pipeline_string(port: int, rtp_caps: str, width: int, jpeg_quality: int) -> str:
    caps = rtp_caps.strip().strip('"').replace("\n", " ")
    caps = "".join(cap for cap in caps if cap not in ("\r",))
    return (
        f'udpsrc name=usrc port={port} caps="{caps}" ! '
        "queue max-size-buffers=2 max-size-time=0 max-size-bytes=0 ! "
        "rtpjitterbuffer latency=33 drop-on-latency=true ! "
        "rtph264depay ! h264parse ! avdec_h264 ! "
        "videoconvert ! videoscale ! "
        f"video/x-raw,width=(int){width},pixel-aspect-ratio=(fraction)1/1 ! "
        f"jpegenc quality={jpeg_quality} ! "
        "appsink name=sink emit-signals=false max-buffers=2 drop=true sync=false"
    )


def _make_pipeline(port: int, rtp_caps: str, width: int, jpeg_quality: int) -> Gst.Pipeline:
    s = _pipeline_string(port, rtp_caps, width, jpeg_quality)
    elt = Gst.parse_launch(s)
    if elt is None or not isinstance(elt, Gst.Pipeline):
        raise RuntimeError("Gst.parse_launch did not return a Gst.Pipeline")
    return elt


def gstreamer_jpeg_frames(pipeline: Gst.Pipeline, stop_check: Callable[[], bool]):
    elt = pipeline.get_by_name("sink")
    if elt is None:
        pipeline.set_state(Gst.State.NULL)
        raise RuntimeError("missing appsink sink")

    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        pipeline.set_state(Gst.State.NULL)
        raise RuntimeError("PLAYING failed (caps / udp port / libav h264 decoder?)")

    bus = pipeline.get_bus()
    wait_ns = 50 * Gst.MSECOND
    poll_ns = Gst.SECOND // 10

    try:
        while stop_check():
            msg = bus.timed_pop_filtered(poll_ns, Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if msg is not None:
                if msg.type == Gst.MessageType.EOS:
                    break
                gerr, dbg = msg.parse_error()
                raise RuntimeError(f"{gerr.message} — {dbg}")

            sample = elt.emit("try-pull-sample", wait_ns)
            if sample is None:
                continue
            buf = sample.get_buffer()
            if buf is None:
                continue
            ok, info = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            try:
                yield bytes(memoryview(info.data))
            finally:
                buf.unmap(info)
    finally:
        pipeline.set_state(Gst.State.NULL)


class Handler(BaseHTTPRequestHandler):
    server_version = "GazeboMJPEGBridge/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        args = self.server.args  # type: ignore[attr-defined]

        if path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            body = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>camera</title></head>
<body style="margin:0;background:#000;overflow:hidden">
<img src="/mjpeg" alt="stream" style="width:100%;height:100%;object-fit:contain;display:block"/>
</body></html>
""".encode()
            self.wfile.write(body)
            return

        if path == "/mjpeg":
            alive = [True]

            try:
                pipeline = _make_pipeline(
                    args.udp_port,
                    args.rtp_caps,
                    args.width,
                    args.jpeg_quality,
                )
            except RuntimeError as e:
                self.send_error(500, str(e))
                return

            self.send_response(200)
            self.send_header(
                "Content-Type",
                f"multipart/x-mixed-replace; boundary={_BOUNDARY_STR}",
            )
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            stop = lambda: alive[0]  # noqa: E731

            try:
                for frame in gstreamer_jpeg_frames(pipeline, stop):
                    try:
                        self.wfile.write(_boundary_header())
                        self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError):
                        break
            except RuntimeError as e:
                if args.verbose:
                    sys.stderr.write(f"gstreamer: {e}\n")
            finally:
                alive[0] = False
            return

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Use /stream in the app iframe, or open /mjpeg directly.\n")
            return

        self.send_error(404, "Not Found")

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if self.server.args.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)


def parse_args() -> argparse.Namespace:
    default_caps = (
        "application/x-rtp,media=(string)video,clock-rate=(int)90000,"
        "encoding-name=(string)H264"
    )
    p = argparse.ArgumentParser(description="GStreamer RTP/UDP (H.264) -> HTTP MJPEG for browser iframe")
    p.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    p.add_argument("--port", type=int, default=8080, help="HTTP port")
    p.add_argument("--udp-port", type=int, default=5600, help="UDP port for udpsrc (gz streaming)")
    p.add_argument(
        "--rtp-caps",
        default=default_caps,
        help="Caps for udpsrc (match your gz / gst-launch caps string)",
    )
    p.add_argument("--width", type=int, default=640, help="scaled width (preserve aspect)")
    p.add_argument("--jpeg-quality", type=int, default=85, help="jpegenc quality 0–100")
    p.add_argument("-v", "--verbose", action="store_true", help="HTTP access log to stderr")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.args = args  # type: ignore[attr-defined]

    print(
        f"GStreamer MJPEG bridge: http://{args.host}:{args.port}/stream\n"
        f"  udpsrc port={args.udp_port}\n"
        "  Set the frontend Gazebo stream URL to /stream .\n"
        "  Ctrl+C to stop.\n",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...", flush=True)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
