from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

import numpy as np
import torch
from espnet2.bin.tts_inference import Text2Speech
from espnet2.text.token_id_converter import TokenIDConverter
from pydantic import BaseModel, Extra, Field


class Mora(BaseModel):
    """
    モーラ（子音＋母音）ごとの情報
    """

    text: str = Field(title="文字")
    consonant: Optional[str] = Field(title="子音の音素")
    consonant_length: Optional[float] = Field(title="子音の音長")
    vowel: str = Field(title="母音の音素")
    vowel_length: float = Field(title="母音の音長")
    pitch: float = Field(title="音高")  # デフォルト値をつけるとts側のOpenAPIで生成されたコードの型がOptionalになる

    def __hash__(self):
        items = [
            (k, tuple(v)) if isinstance(v, List) else (k, v)
            for k, v in self.__dict__.items()
        ]
        return hash(tuple(sorted(items)))


class AccentPhrase(BaseModel):
    """
    アクセント句ごとの情報
    """

    moras: List[Mora] = Field(title="モーラのリスト")
    accent: int = Field(title="アクセント箇所")
    pause_mora: Optional[Mora] = Field(title="後ろに無音を付けるかどうか")
    is_interrogative: bool = Field(default=False, title="疑問系かどうか")

    def __hash__(self):
        items = [
            (k, tuple(v)) if isinstance(v, List) else (k, v)
            for k, v in self.__dict__.items()
        ]
        return hash(tuple(sorted(items)))


class AudioQuery(BaseModel):
    """
    音声合成用のクエリ
    """

    accent_phrases: List[AccentPhrase] = Field(title="アクセント句のリスト")
    speedScale: float = Field(title="全体の話速")
    pitchScale: float = Field(title="全体の音高")
    intonationScale: float = Field(title="全体の抑揚")
    volumeScale: float = Field(title="全体の音量")
    prePhonemeLength: float = Field(title="音声の前の無音時間")
    postPhonemeLength: float = Field(title="音声の後の無音時間")
    outputSamplingRate: int = Field(title="音声データの出力サンプリングレート")
    outputStereo: bool = Field(title="音声データをステレオ出力するか否か")
    kana: Optional[str] = Field(title="[読み取り専用]AquesTalkライクな読み仮名。音声合成クエリとしては無視される")

    def __hash__(self):
        items = [
            (k, tuple(v)) if isinstance(v, List) else (k, v)
            for k, v in self.__dict__.items()
        ]
        return hash(tuple(sorted(items)))


class ParseKanaErrorCode(Enum):
    UNKNOWN_TEXT = "判別できない読み仮名があります: {text}"
    ACCENT_TOP = "句頭にアクセントは置けません: {text}"
    ACCENT_TWICE = "1つのアクセント句に二つ以上のアクセントは置けません: {text}"
    ACCENT_NOTFOUND = "アクセントを指定していないアクセント句があります: {text}"
    EMPTY_PHRASE = "{position}番目のアクセント句が空白です"
    INTERROGATION_MARK_NOT_AT_END = "アクセント句末以外に「？」は置けません: {text}"
    INFINITE_LOOP = "処理時に無限ループになってしまいました...バグ報告をお願いします。"


class ParseKanaError(Exception):
    def __init__(self, errcode: ParseKanaErrorCode, **kwargs):
        self.errcode = errcode
        self.errname = errcode.name
        self.kwargs: Dict[str, str] = kwargs
        err_fmt: str = errcode.value
        self.text = err_fmt.format(**kwargs)


class ParseKanaBadRequest(BaseModel):
    text: str = Field(title="エラーメッセージ")
    error_name: str = Field(
        title="エラー名",
        description="|name|description|\n|---|---|\n"
        + "\n".join(
            [
                "| {} | {} |".format(err.name, err.value)
                for err in list(ParseKanaErrorCode)
            ]
        ),
    )
    error_args: Dict[str, str] = Field(title="エラーを起こした箇所")

    def __init__(self, err: ParseKanaError):
        super().__init__(text=err.text, error_name=err.errname, error_args=err.kwargs)


class SpeakerStyle(BaseModel):
    """
    スピーカーのスタイル情報
    """

    name: str = Field(title="スタイル名")
    id: int = Field(title="スタイルID")


class Speaker(BaseModel):
    """
    スピーカー情報
    """

    name: str = Field(title="名前")
    speaker_uuid: str = Field(title="スピーカーのUUID")
    styles: List[SpeakerStyle] = Field(title="スピーカースタイルの一覧")
    version: str = Field("スピーカーのバージョン")


class StyleInfo(BaseModel):
    """
    スタイルの追加情報
    """

    id: int = Field(title="スタイルID")
    icon: str = Field(title="当該スタイルのアイコンをbase64エンコードしたもの")
    voice_samples: List[str] = Field(title="voice_sampleのwavファイルをbase64エンコードしたもの")


class SpeakerInfo(BaseModel):
    """
    話者の追加情報
    """

    policy: str = Field(title="policy.md")
    portrait: str = Field(title="portrait.pngをbase64エンコードしたもの")
    style_infos: List[StyleInfo] = Field(title="スタイルの追加情報")


class SupportedDevicesInfo(BaseModel):
    """
    対応しているデバイスの情報
    """

    cpu: bool = Field(title="CPUに対応しているか")
    cuda: bool = Field(title="CUDA(GPU)に対応しているか")


class TTSInferenceInitArgs(BaseModel):
    """
    espnet2.bin.tts_inference.Text2Speechの初期化時に渡すパラメータ
    """

    train_config: Union[Path, str] = None
    model_file: Union[Path, str] = None
    threshold: float = 0.5
    minlenratio: float = 0.0
    maxlenratio: float = 10.0
    use_teacher_forcing: bool = False
    use_att_constraint: bool = False
    backward_window: int = 1
    forward_window: int = 3
    speed_control_alpha: float = 1.0
    noise_scale: float = 0.667
    noise_scale_dur: float = 0.8
    vocoder_config: Union[Path, str] = None
    vocoder_file: Union[Path, str] = None
    dtype: str = "float32"
    device: str = "cpu"  # use_gpu引数で上書きされる
    seed: int = 777
    always_fix_seed: bool = False


class TTSInferenceCallArgs(BaseModel):
    """
    espnet2.bin.tts_inference.Text2Speechの呼び出し時に渡すパラメータ
    """

    class Config:
        arbitrary_types_allowed = True

    speech: Optional[Union[torch.Tensor, np.ndarray]] = None
    durations: Optional[Union[torch.Tensor, np.ndarray]] = None
    spembs: Optional[Union[torch.Tensor, np.ndarray]] = None
    sids: Optional[Union[torch.Tensor, np.ndarray]] = None
    lids: Optional[Union[torch.Tensor, np.ndarray]] = None
    decode_conf: Optional[Dict[str, Any]] = None


class TokenIDConverterInitArgs(BaseModel):
    """
    espnet2.text.token_id_converter.TokenIDConverterの呼び出し時に渡すパラメータ
    """

    token_list: Union[Path, str, Iterable[str]]
    unk_symbol: str = "<unk>"


class StyleConfig(SpeakerStyle):
    """
    スタイルの設定のフォーマット
    """

    class Config:
        arbitrary_types_allowed = True

    sampling_rate: int = Field(title="出力サンプリングレート")
    g2p: Literal["pyopenjtalk_accent_with_pause", "pyopenjtalk_prosody"] = Field(
        title="g2pの設定"
    )
    tts_inference_init_args: TTSInferenceInitArgs = Field(
        title="Text2Speechクラス初期化時の引数", default=TTSInferenceInitArgs()
    )
    tts_inference_call_args: TTSInferenceCallArgs = Field(
        title="Text2Speechクラス呼び出し時の引数", default=TTSInferenceCallArgs()
    )
    token_id_converter_init_args: TokenIDConverterInitArgs = Field(
        title="TokenIDConverterクラス初期化時の引数",
    )
    text2speech: Optional[Text2Speech] = Field(
        title="Text2Speechクラスのインスタンス（内部で使用）", default=None
    )
    token_id_converter: Optional[TokenIDConverter] = Field(
        title="TokenIDConverterクラスのインスタンス（内部で使用）", default=None
    )


class SpeakerConfig(Speaker):
    """
    スピーカーの設定のフォーマット
    """

    styles: List[StyleConfig] = Field(title="スタイルの設定")


class EngineConfig(BaseModel, extra=Extra.ignore):
    """
    エンジンの設定のフォーマット
    """

    name: str = Field(title="エンジン名")
    host: str = Field(title="エンジンのホスト", default="127.0.0.1")
    port: int = Field(title="エンジンのポート番号", default=50021)
    engine_uuid: str = Field(title="エンジン固有のUUID")
    engine_version: str = Field(title="エンジンのバージョン")
    min_vvb_version: str = Field(title="要求するVVBridgeの最低限のバージョン", default="0.0.1")
    speakers: List[SpeakerConfig] = Field(title="スピーカー情報")
