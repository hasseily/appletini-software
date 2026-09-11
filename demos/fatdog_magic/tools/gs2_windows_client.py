"""Use the installed gs2-mcp sidecar where CPython lacks AF_UNIX (Windows).

The sidecar owns the native debugger transport; this adapter only calls its
documented MCP tools over stdio. It exposes the smoke test's small Client subset.
"""
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace


class Client:
    def __init__(self):
        self.process = None
        self.sequence = 0

    def rpc(self, method, params):
        self.sequence += 1
        message = {"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params}
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("gs2-mcp closed its output")
            reply = json.loads(line)
            if reply.get("id") == self.sequence:
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                return reply["result"]

    def call(self, name, **arguments):
        reply = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if reply.get("isError"):
            raise RuntimeError(f"{name}: {reply['content']}")
        return reply.get("structuredContent") or json.loads(reply["content"][0]["text"])

    def connect(self, path):
        executable = os.environ.get("GS2_MCP", str(Path.home() / ".local/bin/gs2-mcp.exe"))
        self.process = subprocess.Popen([executable, "--socket", path],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                "clientInfo": {"name": "fatdog-smoke", "version": "1"}})
        self.process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        self.process.stdin.flush()
        self.call("connect", socket=path)

    def hello(self):
        return self.call("hello")

    def close(self):
        if self.process:
            self.process.stdin.close()
            self.process.wait(timeout=5)
            self.process.stdout.close()
            self.process = None

    def quit(self):
        self.call("quit")

    def bp_clear_all(self):
        self.call("bp_clear_all")

    def bp_set(self, *, kind, address):
        return self.call("bp_set", kind="EXEC", address=address)["id"]

    def tap_key(self, scancode):
        self.call("tap_key", scancode=scancode)

    def continue_(self):
        self.call("continue_exec")

    def wait_stopped(self, *, timeout):
        return SimpleNamespace(**self.call("wait_stopped", timeout_s=timeout))

    def read_mem(self, domain, address, length):
        return bytes.fromhex(self.call("read_mem", domain={0: "MAIN", 4: "MAIN_RAW", 5: "MEGAII_RAW"}[domain],
                                       address=address, length=length)["hex"])

    def get_regs(self):
        return bytes.fromhex(self.call("get_regs")["hex"])

    def video_text(self):
        lines = self.call("video_text")["lines"]
        return SimpleNamespace(as_lines=lambda: lines)
