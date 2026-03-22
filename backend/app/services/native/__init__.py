"""
Native PDF 服务模块
"""

__all__ = [
    "NativePipeline",
    "get_native_pipeline",
]


def __getattr__(name: str):
    if name in {"NativePipeline", "get_native_pipeline"}:
        from app.services.native.pipeline import NativePipeline, get_native_pipeline
        return {
            "NativePipeline": NativePipeline,
            "get_native_pipeline": get_native_pipeline,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
