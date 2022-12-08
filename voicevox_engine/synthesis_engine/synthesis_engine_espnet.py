import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import librosa.effects
import numpy as np
import torch
import yaml
from espnet2.bin.tts_inference import Text2Speech
from espnet2.text.token_id_converter import TokenIDConverter
from fastapi import HTTPException
from scipy.signal import resample

from ..model import AccentPhrase, AudioQuery, EngineConfig
from .synthesis_engine_base import SynthesisEngineBase


def query2tokens(query: AudioQuery, g2p_type: str):
    tokens = []
    if g2p_type in ["pyopenjtalk_accent_with_pause", "pyopenjtalk_g2p_accent"]:
        for accent_phrase in query.accent_phrases:
            accent = accent_phrase.accent
            for i, mora in enumerate(accent_phrase.moras):
                if mora.consonant is not None:
                    tokens.append(mora.consonant)
                    tokens.append(str(accent))
                    tokens.append(str((i + 1) - accent))
                tokens.append(mora.vowel)
                tokens.append(str(accent))
                tokens.append(str((i + 1) - accent))
            if (
                accent_phrase.pause_mora is not None
                and g2p_type == "pyopenjtalk_accent_with_pause"
            ):
                tokens.append(accent_phrase.pause_mora.vowel)
        return tokens

    elif g2p_type == "pyopenjtalk_prosody":
        # TODO: 有声、無声フラグ
        for i, accent_phrase in enumerate(query.accent_phrases):
            accent = accent_phrase.accent
            for j, mora in enumerate(accent_phrase.moras):
                if mora.consonant is not None:
                    tokens.append(mora.consonant.lower())
                if mora.vowel == "N":
                    tokens.append(mora.vowel)
                else:
                    tokens.append(mora.vowel.lower())
                if accent_phrase.accent == j + 1 or j == 0:
                    if accent_phrase.accent == j + 1 and j == 0:
                        tokens.append("]")
                    elif j == 0:
                        tokens.append("[")
                    else:
                        tokens.append("]")
            if len(query.accent_phrases) > i + 1:
                if accent_phrase.pause_mora:
                    tokens.append("_")
                else:
                    tokens.append("#")
            else:
                if accent_phrase.is_interrogative:
                    # 最後のアクセント句のみ疑問文判定する
                    tokens.append("?")
                else:
                    tokens.append("$")
        return tokens

    else:
        raise RuntimeError(f"不明なG2Pの種類です。: {g2p_type}")


def get_abs_path(_path: Optional[str], config_path: Path) -> Path:
    if _path is None:
        return None
    _path = Path(_path)
    if _path.root == "":
        return (config_path / _path).resolve(strict=True)
    else:
        return _path.resolve(strict=True)


class SynthesisEngineESPNet(SynthesisEngineBase):
    def __init__(self, engine_dir: Path, use_gpu: bool, load_all_models: bool):
        self.engine_dir = engine_dir.resolve(strict=True)
        assert self.engine_dir.is_dir()

        # if use_gpu:
        #    self.device = "cuda"
        # else:
        self.device = "cpu"

        os.chdir(self.engine_dir)

        self.engine_config = EngineConfig(
            **yaml.safe_load(
                (self.engine_dir / "engine_config.yaml").open(encoding="utf-8")
            )
        )

        self.host = self.engine_config.host
        self.port = self.engine_config.port
        self.engine_version = self.engine_config.engine_version

        # use_gpuの引数で上書きする
        # text2speechとtoken_id_converterを作成する
        for speaker in self.engine_config.speakers:
            for style in speaker.styles:
                style.tts_inference_init_args.device = self.device
                if load_all_models:
                    style.text2speech = Text2Speech(
                        **style.tts_inference_init_args.dict()
                    )
                    style.token_id_converter = TokenIDConverter(
                        **style.token_id_converter_init_args.dict()
                    )
                else:
                    style.text2speech = None
                    style.token_id_converter = None

    @property
    def default_sampling_rate(self) -> Dict[int, int]:
        return {
            style.id: style.sampling_rate
            for speaker in self.engine_config.speakers
            for style in speaker.styles
        }

    @property
    def speakers(self) -> str:
        return json.dumps(
            [
                {
                    "name": speaker.name,
                    "speaker_uuid": speaker.speaker_uuid,
                    "styles": [
                        {"name": style.name, "id": style.id} for style in speaker.styles
                    ],
                    "version": speaker.version,
                }
                for speaker in self.engine_config.speakers
            ]
        )

    @property
    def supported_devices(self) -> Optional[str]:
        return json.dumps(
            {
                "cpu": True,
                "cuda": False,
            }
        )

    @property
    def speaker_info_dir(self) -> Path:
        return (self.engine_dir / "speaker_info").resolve(strict=True)

    def _get_style(self, speaker_id):
        for speaker in self.engine_config.speakers:
            for style in speaker.styles:
                if style.id == speaker_id:
                    _speaker = style
                    break
            else:
                continue
            break
        else:
            raise HTTPException(status_code=404, detail="該当する話者が見つかりません")
        return _speaker

    def _lazy_init(self, speaker_id: int) -> None:
        speaker = self._get_style(speaker_id)
        if speaker.text2speech is None:
            speaker.text2speech = Text2Speech(**speaker.tts_inference_init_args.dict())
        if speaker.token_id_converter is None:
            speaker.token_id_converter = TokenIDConverter(
                **speaker.token_id_converter_init_args.dict()
            )
            assert speaker.token_id_converter is not None

    def initialize_speaker_synthesis(self, speaker_id: int):
        self._lazy_init(speaker_id)

    def is_initialized_speaker_synthesis(self, speaker_id: int) -> bool:
        speaker = self._get_style(speaker_id)
        return (
            speaker.text2speech is not None and speaker.token_id_converter is not None
        )

    def replace_phoneme_length(
        self, accent_phrases: List[AccentPhrase], speaker_id: int
    ) -> List[AccentPhrase]:
        """
        accent_phrasesの母音・子音の長さを設定する
        Parameters
        ----------
        accent_phrases : List[AccentPhrase]
            アクセント句モデルのリスト
        speaker_id : int
            話者ID
        Returns
        -------
        accent_phrases : List[AccentPhrase]
            母音・子音の長さが設定されたアクセント句モデルのリスト
        """
        # 母音・子音の長さを設定するのは不可能なのでそのまま返す
        return accent_phrases

    def replace_mora_pitch(
        self, accent_phrases: List[AccentPhrase], speaker_id: int
    ) -> List[AccentPhrase]:
        """
        accent_phrasesの音高(ピッチ)を設定する
        Parameters
        ----------
        accent_phrases : List[AccentPhrase]
            アクセント句モデルのリスト
        speaker_id : int
            話者ID
        Returns
        -------
        accent_phrases : List[AccentPhrase]
            音高(ピッチ)が設定されたアクセント句モデルのリスト
        """
        # 音高を設定するのは不可能なのでそのまま返す
        return accent_phrases

    def _synthesis_impl(self, query: AudioQuery, speaker_id: int):
        """
        音声合成クエリから音声合成に必要な情報を構成し、実際に音声合成を行う
        Parameters
        ----------
        query : AudioQuery
            音声合成クエリ
        speaker_id : int
            話者ID
        Returns
        -------
        wave : numpy.ndarray
            音声合成結果
        """
        self._lazy_init(speaker_id)
        _speaker = self._get_style(speaker_id)

        assert _speaker.text2speech is not None
        assert _speaker.token_id_converter is not None

        with torch.no_grad():
            tokens = query2tokens(query, _speaker.g2p)
            ids = np.array(_speaker.token_id_converter.tokens2ids(tokens))
            wave = _speaker.text2speech(ids, **_speaker.tts_inference_call_args.dict())
            wave = wave["wav"].view(-1).cpu().numpy()

        # 無音時間トリミング
        wave, _ = librosa.effects.trim(wave)
        # 音量
        if query.volumeScale != 1:
            wave *= query.volumeScale
        # 開始無音
        if query.prePhonemeLength != 0:
            wave = np.concatenate(
                [
                    np.zeros(
                        int(
                            self.default_sampling_rate[speaker_id]
                            * query.prePhonemeLength
                        )
                    ),
                    wave,
                ],
                0,
            )
        # 終了無音
        if query.postPhonemeLength != 0:
            wave = np.concatenate(
                [
                    wave,
                    np.zeros(
                        int(
                            self.default_sampling_rate[speaker_id]
                            * query.postPhonemeLength
                        )
                    ),
                ],
                0,
            )
        # サンプリングレート変更
        wave = resample(
            wave,
            query.outputSamplingRate
            * len(wave)
            // self.default_sampling_rate[speaker_id],
        )
        # ステレオ化
        if query.outputStereo:
            wave = np.array([wave, wave]).T

        return wave
