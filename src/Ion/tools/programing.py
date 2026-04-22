import logging
import io
import json
import asyncio
import traceback
import requests
import httpx
from contextlib import redirect_stdout, redirect_stderr
from .registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


# 依然需要 Lock，因为 sys.stdout 是全局的
_python_exec_lock = asyncio.Lock()
_httpx_client = httpx.AsyncClient(verify=False)  # 忽略SSL证书验证


async def _python_exec(code: str) -> str:
    """
    Python脚本执行接口 (异步非阻塞).
    支持自动同步全局会话的 Cookie，并捕获 script 中的 print 输出。
    """

    def _run_script():
        # 使用 StringIO 捕获流
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        # 准备沙盒环境
        sandbox_session = requests.Session()

        # 1. 优化后的 Cookie 同步 (httpx -> requests)
        try:
            for cookie in _httpx_client.cookies.jar:
                if not cookie.value:
                    continue
                sandbox_session.cookies.set(
                    cookie.name, cookie.value, domain=cookie.domain, path=cookie.path
                )
        except Exception as e:
            logger.warning(f"Cookie sync failed: {e}")

        global_scope = {
            "requests": requests,
            "session": sandbox_session,
            "json": json,
            "__name__": "__main__",
        }

        try:
            # 2. 预编译，提升性能并提前发现语法错误
            compiled_code = compile(code, "<string>", "exec")

            # 3. 使用 contextlib 安全地重定向输出
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compiled_code, global_scope)
            return tool_result(
                success=True,
                output=stdout_buf.getvalue(),
                error=stderr_buf.getvalue(),
                cookies=sandbox_session.cookies.get_dict(),
            )

        except SyntaxError as e:
            return tool_error(
                message=f"Syntax Error: {e.msg} (Line {e.lineno}).",
                success=False,
            )
        except ImportError as e:
            return tool_error(
                message=f"Import error: {e}",
                success=False,
                fix_suggestion="Please install the missing module using pip install <module_name>.",
            )
        except BaseException as e:
            # 4. 捕获包括 SystemExit 在内的所有异常，并记录堆栈
            error_msg = traceback.format_exc()
            return tool_error(
                message=str(e),
                success=False,
                output=stdout_buf.getvalue(),
                error=stderr_buf.getvalue(),
                traceback=error_msg,
            )
        finally:
            stdout_buf.close()
            stderr_buf.close()

    # 执行逻辑
    async with _python_exec_lock:
        loop = asyncio.get_running_loop()
        result = ""
        try:
            result = await loop.run_in_executor(None, _run_script)

            data = json.loads(result)
            # 5. 回写 Cookie 到全局 httpx client
            if isinstance(data, dict) and data.get("success") and "cookies" in data:
                new_cookies = data.pop("cookies")
                _httpx_client.cookies.update(new_cookies)

        except Exception as e:
            logger.warning(f"Thread execution failed: {e}")
        finally:
            return result


PYTHON_EXEC_SCHEMA = {
    "type": "function",
    "function": {
        "name": "python_exec",
        "description": "Execute Python code in a restricted environment and return stdout.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"}
            },
            "required": ["code"],
        },
    },
}

registry.register(
    name="python_exec",
    toolset="builtin",
    schema=PYTHON_EXEC_SCHEMA,
    handler=_python_exec,
    is_async=True,
    description="Execute Python code in a restricted environment and return stdout.",
    emoji="🐍",
    max_result_size_chars=10000,
)
