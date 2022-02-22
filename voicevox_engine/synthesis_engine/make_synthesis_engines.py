import sys
import traceback
from pathlib import Path
from typing import Dict

from .synthesis_engine_base import SynthesisEngineBase
from .synthesis_engine_espnet import SynthesisEngineESPNet


def make_synthesis_engines(
    engine_dir: Path,
    use_gpu: bool,
    enable_mock: bool = True,
) -> Dict[str, SynthesisEngineBase]:
    """
    音声ライブラリをロードして、音声合成エンジンを生成

    Parameters
    ----------
    engine_dir: Path
        VVBridgeエンジンへのパス
    use_gpu: bool
        音声ライブラリに強制的に GPU を使わせるか否か
    enable_mock: bool, optional, default=True
        コア読み込みに失敗したとき、代わりにmockを使用するかどうか
    """
    synthesis_engines = {}
    try:
        if engine_dir is None:
            raise Exception("engine_dirが指定されていません")
        _synthesis_engine = SynthesisEngineESPNet(
            engine_dir=engine_dir, use_gpu=use_gpu
        )
        synthesis_engines[_synthesis_engine.engine_version] = _synthesis_engine
    except Exception:
        if not enable_mock:
            raise
        traceback.print_exc()
        print(
            "Notice: mock-library will be used.",
            file=sys.stderr,
        )
        from ..dev.core import metas as mock_metas
        from ..dev.core import supported_devices as mock_supported_devices
        from ..dev.synthesis_engine import MockSynthesisEngine

        if "0.0.0" not in synthesis_engines:
            synthesis_engines["0.0.0"] = MockSynthesisEngine(
                speakers=mock_metas(), supported_devices=mock_supported_devices()
            )

    return synthesis_engines
