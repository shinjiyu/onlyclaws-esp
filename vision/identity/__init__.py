"""Face identity package (SFace gallery)."""

from .gallery import FaceGallery, FaceRecord
from .recognize import IdResult, identify_faces, sface_available

__all__ = [
    "FaceGallery",
    "FaceRecord",
    "IdResult",
    "identify_faces",
    "sface_available",
]
