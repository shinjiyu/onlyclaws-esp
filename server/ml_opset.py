"""TFLite Micro operator sets the firmware ml plugin can run.

Mirrors registerOpsetV1() in rlcd/src/ml_engine.cpp; tests/test_ml_registry.py
fails if the two drift. Op sets are append-only: a new firmware release that
registers more ops adds OPSET_V2 = OPSET_V1 | {...} and bumps OPSET_VERSION.
"""

from __future__ import annotations

OPSET_VERSION = 1

# Firmware resolver method (AddXxx without "Add") -> TFLite BuiltinOperator code.
BUILTINS_V1: dict[str, int] = {
    "Add": 0,
    "AveragePool2D": 1,
    "Cast": 53,
    "Concatenation": 2,
    "Conv2D": 3,
    "DepthwiseConv2D": 4,
    "Dequantize": 6,
    "Div": 42,
    "ExpandDims": 70,
    "FullyConnected": 9,
    "HardSwish": 117,
    "LeakyRelu": 98,
    "Logistic": 14,
    "MaxPool2D": 17,
    "Maximum": 55,
    "Mean": 40,
    "Minimum": 57,
    "Mul": 18,
    "Pack": 83,
    "Pad": 34,
    "Quantize": 114,
    "Relu": 19,
    "Relu6": 21,
    "Reshape": 22,
    "Shape": 77,
    "Slice": 65,
    "Softmax": 25,
    "Split": 49,
    "Squeeze": 43,
    "StridedSlice": 45,
    "Sub": 41,
    "Tanh": 28,
    "Transpose": 39,
    "Unpack": 88,
}

# Firmware resolver method -> custom op name in the .tflite (TFLM signal library).
CUSTOMS_V1: dict[str, str] = {
    "Window": "SignalWindow",
    "FftAutoScale": "SignalFftAutoScale",
    "Rfft": "SignalRfft",
    "Energy": "SignalEnergy",
    "FilterBank": "SignalFilterBank",
    "FilterBankSquareRoot": "SignalFilterBankSquareRoot",
    "FilterBankSpectralSubtraction": "SignalFilterBankSpectralSubtraction",
    "PCAN": "SignalPCAN",
    "FilterBankLog": "SignalFilterBankLog",
    "Framer": "SignalFramer",
    "Stacker": "SignalStacker",
}

BUILTIN_CUSTOM = 32

OPSETS: dict[int, tuple[frozenset[int], frozenset[str]]] = {
    1: (frozenset(BUILTINS_V1.values()), frozenset(CUSTOMS_V1.values())),
}


def describe(version: int = OPSET_VERSION) -> dict[str, object]:
    """Human/agent-readable op set (GET /api/ml/opset)."""
    if version != 1:
        raise KeyError(version)
    return {
        "opset": version,
        "builtins": sorted(BUILTINS_V1),
        "custom": sorted(CUSTOMS_V1.values()),
    }
