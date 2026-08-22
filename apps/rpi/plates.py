"""Gestion sûre des templates de plaques depuis l'administration."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from steamcore.recognition._images import find_template_images

PLATE_ID_PATTERN = re.compile(r"^plate_[a-z0-9_]{1,58}$")
ARCHIVE_ID_PATTERN = re.compile(r"^(plate_[a-z0-9_]{1,58})__(\d{8}T\d{6})(?:_(\d+))?$")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_FILES = 30
PROTECTED_PLATES = {"plate_ready_check"}


class PlateError(ValueError):
    pass


class PlateConflictError(PlateError):
    pass


class PlateStore:
    def __init__(self, plates_dir: str | Path, trash_dir: str | Path):
        self.plates_dir = Path(plates_dir).resolve()
        self.trash_dir = Path(trash_dir).resolve()

    @staticmethod
    def validate_plate_id(plate_id: str) -> str:
        plate_id = plate_id.strip().lower()
        if not PLATE_ID_PATTERN.fullmatch(plate_id):
            raise PlateError("identifiant attendu: plate_nom (lettres, chiffres, _)")
        return plate_id

    @staticmethod
    def _validate_filename(filename: str) -> str:
        if Path(filename).name != filename or not filename:
            raise PlateError("nom de fichier invalide")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", filename):
            raise PlateError("nom de fichier limité à lettres, chiffres, ., _ et -")
        if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
            raise PlateError("format accepté: jpg, jpeg, png ou webp")
        return filename

    def list_active(self) -> list[dict]:
        if not self.plates_dir.exists():
            return []
        result = []
        for folder in sorted(self.plates_dir.iterdir()):
            if not folder.is_dir() or not PLATE_ID_PATTERN.fullmatch(folder.name):
                continue
            images = find_template_images(folder)
            result.append(
                {
                    "plate_id": folder.name,
                    "images": [p.name for p in images],
                    "image_count": len(images),
                    "protected": folder.name in PROTECTED_PLATES,
                }
            )
        return result

    def list_archived(self) -> list[dict]:
        if not self.trash_dir.exists():
            return []
        result = []
        for folder in sorted(self.trash_dir.iterdir(), reverse=True):
            match = ARCHIVE_ID_PATTERN.fullmatch(folder.name)
            if not folder.is_dir() or not match:
                continue
            result.append(
                {
                    "archive_id": folder.name,
                    "plate_id": match.group(1),
                    "image_count": len(find_template_images(folder)),
                }
            )
        return result

    def add_images(self, plate_id: str, files: list[tuple[str, bytes]]) -> dict:
        plate_id = self.validate_plate_id(plate_id)
        if not files:
            raise PlateError("aucune image fournie")
        if (
            len(files) > MAX_UPLOAD_FILES
            or sum(len(content) for _name, content in files) > MAX_UPLOAD_BYTES
        ):
            raise PlateError("upload limité à 30 images et 50 Mio au total")
        target_dir = self._active_path(plate_id)
        prepared = []
        names = set()
        for filename, content in files:
            filename = self._validate_filename(filename)
            if filename in names:
                raise PlateConflictError(
                    f"fichier dupliqué dans la requête: {filename}"
                )
            names.add(filename)
            if not content or len(content) > MAX_IMAGE_BYTES:
                raise PlateError("image vide ou supérieure à 10 Mio")
            decoded = cv2.imdecode(
                np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if decoded is None:
                raise PlateError(f"image illisible: {filename}")
            target = (target_dir / filename).resolve()
            self._require_parent(target, target_dir)
            if target.exists():
                raise PlateConflictError(f"fichier déjà présent: {filename}")
            prepared.append((filename, content, target))

        target_dir.mkdir(parents=True, exist_ok=True)
        temporaries = []
        try:
            for _filename, content, target in prepared:
                temporary = target.with_name(f".{target.name}.upload")
                temporary.write_bytes(content)
                temporaries.append((temporary, target))
            for temporary, target in temporaries:
                os.replace(temporary, target)
        finally:
            for temporary, _target in temporaries:
                temporary.unlink(missing_ok=True)
        return {"plate_id": plate_id, "added": [item[0] for item in prepared]}

    def archive(self, plate_id: str) -> dict:
        plate_id = self.validate_plate_id(plate_id)
        if plate_id in PROTECTED_PLATES:
            raise PlateError("cette plaque système est protégée")
        source = self._active_path(plate_id)
        if not source.is_dir():
            raise PlateError("plaque introuvable")
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        target = self.trash_dir / f"{plate_id}__{stamp}"
        suffix = 1
        while target.exists():
            target = self.trash_dir / f"{plate_id}__{stamp}_{suffix}"
            suffix += 1
        shutil.move(str(source), str(target))
        return {"plate_id": plate_id, "archive_id": target.name}

    def restore(self, archive_id: str) -> dict:
        match = ARCHIVE_ID_PATTERN.fullmatch(archive_id)
        if not match:
            raise PlateError("archive invalide")
        plate_id = match.group(1)
        source = (self.trash_dir / archive_id).resolve()
        self._require_parent(source, self.trash_dir)
        if not source.is_dir():
            raise PlateError("archive introuvable")
        target = self._active_path(plate_id)
        if target.exists():
            raise PlateConflictError("une plaque active porte déjà ce nom")
        self.plates_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return {"plate_id": plate_id, "archive_id": archive_id}

    def image_path(self, plate_id: str, filename: str) -> Path:
        plate_id = self.validate_plate_id(plate_id)
        filename = self._validate_filename(filename)
        folder = self._active_path(plate_id)
        target = (folder / filename).resolve()
        self._require_parent(target, folder)
        if not target.is_file():
            raise PlateError("image introuvable")
        return target

    def _active_path(self, plate_id: str) -> Path:
        target = (self.plates_dir / plate_id).resolve()
        self._require_parent(target, self.plates_dir)
        return target

    @staticmethod
    def _require_parent(target: Path, parent: Path) -> None:
        if target.parent != parent.resolve():
            raise PlateError("chemin hors du dossier autorisé")
