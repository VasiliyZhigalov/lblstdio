"""Validate staged uploads without writing any project data."""
import json
import math
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image
import yaml
from app.domain.exceptions import DomainValidationException as Invalid
from app.domain.services.yolo_label_import import (
    _normalize_path, _check_zip_member, pair_images_and_labels, parse_yolo_label_file,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def inspect_dataset(root: Path, uploads: list, task: str, kind: str):
    files = {}
    expanded = root / "expanded"
    expanded.mkdir(exist_ok=True)
    total_bytes = 0
    for original, path in uploads:
        if path.suffix.lower() == ".zip" or original.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > 10000: raise Invalid("В архиве более 10000 файлов")
                total = sum(m.file_size for m in members)
                if total > 2 * 1024**3: raise Invalid("Распакованный архив больше 2 ГБ")
                for member in members:
                    if member.is_dir(): continue
                    total_bytes = _check_zip_member(member, total_uncompressed=total_bytes)
                    name = _normalize_path(member.filename)
                    if name in files: raise Invalid(f"Повторяющийся путь: {name}")
                    target = expanded / str(len(files))
                    with archive.open(member) as src, target.open("wb") as dst: shutil.copyfileobj(src, dst)
                    files[name] = target
        else:
            name = _normalize_path(original)
            if name in files: raise Invalid(f"Повторяющийся путь: {name}")
            files[name] = path
    images = {n: p for n, p in files.items() if PurePosixPath(n).suffix.lower() in IMAGE_EXTENSIONS}
    if not images or len(images) > 5000: raise Invalid("Нужно от 1 до 5000 изображений")
    names, records = [], []
    dimensions = {}
    for name, path in images.items():
        try:
            with Image.open(path) as image:
                w, h = image.size
                if w * h > 100_000_000: raise Invalid(f"Слишком большое изображение: {name}")
                image.verify()
            dimensions[name] = (w, h)
        except (OSError, ValueError) as exc: raise Invalid(f"Поврежденное изображение: {name}") from exc
    def record(name, boxes=None, label=None, background=False):
        parts = PurePosixPath(name).parts
        split = next(("valid" if p in {"val", "valid", "validation"} else p for p in parts if p in {"train", "val", "valid", "validation", "test"}), "train")
        return {"name": name, "path": str(images[name]), "width": dimensions[name][0], "height": dimensions[name][1], "boxes": boxes or [], "label": label, "background": background, "split": split}
    if kind == "images":
        return {"format": "Изображения", "names": [], "records": [record(n) for n in images]}
    coco_files = []
    for n, path in files.items():
        if n.lower().endswith(".json"):
            try: data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (ValueError, UnicodeError) as exc: raise Invalid(f"Некорректный JSON: {n}") from exc
            if isinstance(data, dict) and {"images", "annotations", "categories"} <= data.keys(): coco_files.append((n, data))
    if coco_files:
        if task != "DETECTION": raise Invalid("COCO detection подходит только для проекта детекции")
        used = set()
        for json_name, data in coco_files:
            categories = {c["id"]: str(c["name"]).strip() for c in data["categories"]}
            for name in categories.values():
                if name not in names: names.append(name)
            boxes_by_image = {}
            for box in data["annotations"]: boxes_by_image.setdefault(box["image_id"], []).append(box)
            for image in data["images"]:
                raw = _normalize_path(image["file_name"])
                candidates = [n for n in images if n == raw or n == str(PurePosixPath(json_name).parent / raw) or n.endswith("/" + raw)]
                if len(candidates) != 1: raise Invalid(f"COCO: не найден однозначный файл {raw}")
                name = candidates[0]
                if name in used: raise Invalid(f"COCO: повторное изображение {name}")
                used.add(name)
                w, h = dimensions[name]
                if image.get("width", w) != w or image.get("height", h) != h: raise Invalid(f"COCO: размеры не совпадают у {name}")
                boxes = []
                for b in boxes_by_image.get(image["id"], []):
                    if "bbox" not in b: raise Invalid("COCO: поддерживаются прямоугольники bbox")
                    x, y, bw, bh = b["bbox"]
                    if b["category_id"] not in categories: raise Invalid("COCO: неизвестный category_id")
                    boxes.append([names.index(categories[b["category_id"]]), (x+bw/2)/w, (y+bh/2)/h, bw/w, bh/h])
                records.append(record(name, boxes, background=not boxes))
        records.extend(record(n) for n in images if n not in used)
        fmt = "COCO"
    elif task == "CLASSIFICATION":
        for name in images:
            parent = PurePosixPath(name).parent.name
            if not parent or parent in {"train", "val", "valid", "test", "images"}: raise Invalid("Для классификации нужны папки с названиями классов")
            if parent not in names: names.append(parent)
            records.append(record(name, label=names.index(parent)))
        fmt = "Папки классов"
    else:
        for name, path in files.items():
            basename = PurePosixPath(name).name.lower()
            if basename in {"data.yaml", "data.yml"}:
                data = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
                raw = data.get("names", [])
                if isinstance(raw, dict):
                    try:
                        indexed = {int(k): str(v).strip() for k, v in raw.items()}
                        if sorted(indexed) != list(range(len(indexed))): raise ValueError()
                        raw = [indexed[i] for i in range(len(indexed))]
                    except (ValueError, TypeError): raise Invalid("YOLO: индексы классов должны идти от 0 без пропусков")
                if not isinstance(raw, list): raise Invalid("YOLO: names должен быть списком или словарём")
                names = [str(v).strip() for v in raw]
            elif basename == "classes.txt" and not names: names = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        labels = {n: p.read_bytes() for n, p in files.items() if n.lower().endswith(".txt") and PurePosixPath(n).name.lower() != "classes.txt"}
        pairs = pair_images_and_labels(images, labels)
        for name in images:
            label_name = pairs.get(name)
            parsed = parse_yolo_label_file(labels[label_name].decode("utf-8-sig")) if label_name else []
            boxes = [[b.class_index, b.x_center, b.y_center, b.width, b.height] for b in parsed]
            records.append(record(name, boxes, background=label_name is not None and not boxes))
        if not names: raise Invalid("Не найдены названия классов. Добавьте data.yaml или classes.txt в датасет")
        fmt = "YOLO"
    if any(not n or len(n) > 255 for n in names) or len(set(names)) != len(names): raise Invalid("Имена классов должны быть непустыми и уникальными")
    for r in records:
        for index, x, y, w, h in r["boxes"]:
            if index < 0 or index >= len(names): raise Invalid(f"{r['name']}: неизвестный индекс класса {index}")
            if not all(math.isfinite(v) for v in (x, y, w, h)) or not (0 < w <= 1 and 0 < h <= 1 and 0 <= x-w/2 and x+w/2 <= 1.000001 and 0 <= y-h/2 and y+h/2 <= 1.000001): raise Invalid(f"{r['name']}: рамка выходит за границы изображения")
    return {"format": fmt, "names": names, "records": records}


def inspect_model(path: Path, task: str):
    from ultralytics import YOLO
    model = YOLO(str(path))
    actual = "CLASSIFICATION" if model.task == "classify" else "DETECTION" if model.task == "detect" else None
    if actual != task: raise Invalid(f"Тип модели {model.task} не соответствует проекту")
    raw = getattr(model.model, "names", None)
    names = [str(raw[i]) for i in range(len(raw))] if raw else []
    head = model.model.model[-1]
    class_count = getattr(head, "nc", None) or getattr(getattr(head, "linear", None), "out_features", None)
    if class_count is not None and names and len(names) != class_count:
        raise Invalid("Количество названий классов не совпадает с выходами модели")
    return {"format": "YOLO .pt", "names": names, "records": [], "model_path": str(path), "task": actual, "class_count": class_count}
