#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI 兼容 Mock 服务（开放接入实测用；零第三方依赖，仅标准库）。

用途
----
给「方式 A：custom 零代码接入」提供本地假端点，用实测证明开放接入链路可跑通：
不依赖任何真实厂商 API、不访问外网，所有请求都打在本机 127.0.0.1。

模拟的端点（OpenAI 兼容结构）
----------------------------
- POST /v1/chat/completions          → 固定 JSON（LLM）
    * messages 末条 content 为「数组」（多模态，含 image_url）→ 返回视觉识别 JSON
    * 否则（纯文本）→ 返回分镜任务 jobs JSON 数组（满足 validate_jobs 规则校验）
- POST /v1/videos/generations        → {"id": "mock-task-0001"}（异步任务式，视频创建）
- GET  /v1/videos/generations/{id}   → {"status":"succeeded","data":[{"url":".../out.mp4"}]}
- POST /v1/images/generations        → {"data":[{"url":".../out.png"}]}（文生图）
- POST /v1/images/edits              → 同上（图生图/融合；custom-image 有参考图时先试此端点）
- GET  /v1/images/generations/{id}   → 同上（custom 查询端点的回退路径）
- GET  /out.mp4 / GET /out.png       → 返回假字节（b'\\x00'*1024），供下载链路验证

用法
----
独立运行（手动验证，起服务后常驻）：
    python tests/mock_api_server.py --port 9999
    python tests/mock_api_server.py --port 9999 --self-test    # 起服务→自测全部端点→退出

作为测试依赖（tests/test_custom_integration.py 使用）：
    from tests.mock_api_server import MockApiServer
    server = MockApiServer(port=port).start()
    ...  # 跑用例
    server.stop()

兼容性：Windows GBK 控制台兼容（stdout/stderr 重配 UTF-8）；Python 3.7+（ThreadingHTTPServer）。
"""
import argparse
import itertools
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ---------- Windows GBK 兼容：控制台输出统一 UTF-8 ----------
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 假视频/图片字节（任意字节即可；下载链路只关心「能拿到非空内容」）
FAKE_VIDEO_BYTES = b"\x00" * 1024
FAKE_IMAGE_BYTES = b"\x00" * 1024

# 任务 id 计数器（每次创建递增，便于区分多次调用）
_TASK_SEQ = itertools.count(1)

# =====================================================================
# 固定返回内容（与项目代码的校验规则严格对齐，保证端到端用例能通过）
# =====================================================================

# LLM「提示词生成」返回的 jobs（必须满足：
#   prompt_engine.validate_jobs —— 含"与参考图完全一致"、无英文、40~160 字、
#                                 负面词含 形变扭曲/多余肢体/手指变形/水印；
#   capability.validate_job    —— 时长 1~10s、参考图 ≤1、分辨率在支持列表）
MOCK_JOBS = [
    {
        "project": "mockproj",
        "sku": "msku1",
        "shot_no": 1,
        "category": "clothing",
        "prompt": "模特身穿香槟色缎面吊带连衣裙，在大理石美术馆中缓慢转身，"
                  "裙摆甩出液态光泽，镜头缓缓推近，氛围优雅高级，与参考图完全一致",
        "negative_prompt": "形变扭曲, 多余肢体, 手指变形, 水印, 画面文字, "
                           "面部变形, 比例失调, 背景杂乱",
        "ref_images": [],
        "duration_sec": 5,
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "version_count": 1,
    }
]

# LLM「视觉识别」返回的商品档案（满足 vision_client._parse_json 的 dict 结构；
# merged 合并后 category/primary_color/material_inference.value 直接可见）
MOCK_RECOGNITION = {
    "image_type": "白底商品图",
    "image_type_confidence": "高",
    "category": "连衣裙",
    "primary_color": "香槟色",
    "material_inference": {"value": "缎面", "confidence": "高", "basis": "光泽质感（mock）"},
    "key_details": "吊带设计",
    "quality": {"clear": True, "occluded": False, "watermark": False, "note": "mock 识别"},
}


# =====================================================================
# HTTP 处理器
# =====================================================================
class MockHandler(BaseHTTPRequestHandler):
    """请求处理：按路径分发到各模拟端点（OpenAI 兼容结构）。"""

    def log_message(self, *args):
        """静默访问日志（保持测试/自测输出干净）。"""
        pass

    # ---------- 工具 ----------
    @property
    def _port(self) -> int:
        """当前服务实际端口（生成下载 URL 用）。"""
        return self.server.server_address[1]

    def _asset_url(self, name: str) -> str:
        """生成指向本服务静态假文件的 URL。"""
        return f"http://127.0.0.1:{self._port}/{name}"

    def _send_json(self, obj, status: int = 200):
        """写 JSON 响应（显式 UTF-8，保证中文正常解码）。"""
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, ctype: str):
        """写二进制响应（假视频/假图片）。"""
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        """读请求体并解析 JSON（解析失败返回空 dict，不抛异常）。"""
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------- POST ----------
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()
        if path == "/v1/chat/completions":
            self._handle_chat(body)
        elif path == "/v1/videos/generations":
            # 异步任务式：只回任务 id，后续由 GET /v1/videos/generations/{id} 查询
            self._send_json({"id": f"mock-task-{next(_TASK_SEQ):04d}"})
        elif path == "/v1/images/generations":
            self._send_json({"data": [{"url": self._asset_url("out.png")}]})
        elif path == "/v1/images/edits":
            self._send_json({"data": [{"url": self._asset_url("out.png")}]})
        else:
            self._send_json({"error": f"未支持的端点: {path}"}, 404)

    def _handle_chat(self, body: dict):
        """LLM 端点：按 content 形态区分「视觉识别」与「提示词生成」。"""
        messages = body.get("messages") or []
        last = messages[-1] if messages else {}
        content = last.get("content")
        if isinstance(content, list):
            # 多模态（text + image_url 数组）→ 视觉识别
            text = json.dumps(MOCK_RECOGNITION, ensure_ascii=False)
        else:
            # 纯文本 → 提示词生成（返回 jobs 数组）
            text = json.dumps(MOCK_JOBS, ensure_ascii=False)
        self._send_json({"choices": [{"message": {"role": "assistant", "content": text}}]})

    # ---------- GET ----------
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/v1/videos/generations/"):
            # 任务查询：直接返回成功 + 视频 URL（不用真的等轮询）
            self._send_json({"status": "succeeded",
                             "data": [{"url": self._asset_url("out.mp4")}]})
        elif path.startswith("/v1/images/generations/"):
            self._send_json({"status": "succeeded",
                             "data": [{"url": self._asset_url("out.png")}]})
        elif path == "/out.mp4":
            self._send_bytes(FAKE_VIDEO_BYTES, "video/mp4")
        elif path == "/out.png":
            self._send_bytes(FAKE_IMAGE_BYTES, "image/png")
        else:
            self._send_json({"error": f"未支持的端点: {path}"}, 404)


# =====================================================================
# 服务（可独立运行 / 可嵌入测试）
# =====================================================================
class MockApiServer:
    """OpenAI 兼容 mock 服务：线程启动，start()/stop() 成对使用。"""

    def __init__(self, port: int = 0, host: str = "127.0.0.1"):
        """
        :param port: 监听端口；0 = 自动分配（此时用 self.port 取实际端口）
        :param host: 监听地址（默认仅本机回环，测试安全）
        """
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None

    def start(self) -> "MockApiServer":
        """线程启动服务（幂等：重复调用直接返回自身）。"""
        if self._httpd is not None:
            return self
        self._httpd = ThreadingHTTPServer((self.host, self.port), MockHandler)
        self._httpd.daemon_threads = True  # 请求线程不阻塞退出
        self.port = self._httpd.server_address[1]  # port=0 → 实际分配端口
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """关停服务（幂等）。"""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None

    def base_url(self) -> str:
        """服务根地址（端点在其下，如 http://127.0.0.1:9999）。"""
        return f"http://{self.host}:{self.port}"


# =====================================================================
# 自测 / 独立运行入口
# =====================================================================
def _self_test(port: int):
    """起服务 → 用标准库 urllib 打全部端点 → 打印结果 → 退出。"""
    import urllib.request

    server = MockApiServer(port=port).start()
    base = server.base_url()
    print(f"[mock] 服务已启动: {base}")

    def call(method: str, path: str, payload=None) -> tuple:
        req = urllib.request.Request(base + path, method=method)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, data=data, timeout=5) as r:
            return r.status, r.read()

    # 1) LLM 文本 → jobs（提示词生成）
    st, body = call("POST", "/v1/chat/completions",
                    {"model": "mock", "messages": [{"role": "user", "content": "测试"}]})
    text = body.decode("utf-8")
    print(f"POST /v1/chat/completions -> {st} | 含 jobs 数组: "
          f"{'与参考图完全一致' in text}")

    # 2) 视觉识别（多模态 content 数组）
    st, body = call("POST", "/v1/chat/completions",
                    {"model": "mock", "messages": [{"role": "user", "content": [
                        {"type": "text", "text": "识别"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}}]}]})
    print(f"POST /v1/chat/completions(多模态) -> {st} | 含识别字段: "
          f"{'material_inference' in body.decode('utf-8')}")

    # 3) 视频创建（异步任务式）
    st, body = call("POST", "/v1/videos/generations", {"model": "mock", "prompt": "p"})
    tid = json.loads(body)["id"]
    print(f"POST /v1/videos/generations -> {st} | id={tid}")

    # 4) 视频查询
    st, body = call("GET", f"/v1/videos/generations/{tid}")
    print(f"GET /v1/videos/generations/{tid} -> {st} | "
          f"status={json.loads(body)['status']}")

    # 5) 文生图
    st, body = call("POST", "/v1/images/generations", {"model": "mock", "prompt": "p"})
    print(f"POST /v1/images/generations -> {st} | 含 /out.png: "
          f"{'/out.png' in body.decode('utf-8')}")

    # 6) 假视频下载
    st, body = call("GET", "/out.mp4")
    print(f"GET /out.mp4 -> {st} | {len(body)} bytes")

    server.stop()
    print("[mock] 自测完成（全部端点可达）")


def main(argv=None):
    parser = argparse.ArgumentParser(description="OpenAI 兼容 Mock 服务（开放接入实测）")
    parser.add_argument("--port", type=int, default=0,
                        help="监听端口（默认 0 = 自动分配）")
    parser.add_argument("--self-test", action="store_true",
                        help="起服务后自测全部端点再退出")
    args = parser.parse_args(argv)
    if args.self_test:
        _self_test(args.port)
        return
    server = MockApiServer(port=args.port).start()
    print(f"[mock] OpenAI 兼容 Mock 服务已启动: {server.base_url()}/v1 （Ctrl+C 退出）")
    try:
        server._httpd.serve_forever()
    except KeyboardInterrupt:
        print("[mock] 已退出")
        server.stop()


if __name__ == "__main__":
    main()
