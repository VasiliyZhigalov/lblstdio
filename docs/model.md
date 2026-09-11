# СПЕЦИФИКАЦИЯ ДОМЕННОЙ МОДЕЛИ ДАННЫХ
## Система полуавтоматической разметки и активного обучения с обязательной верификацией человеком (Human-in-the-Loop Domain Model)

---

## 1. Фундаментальный принцип системы (Core Invariant)

> **Критическое бизнес-правило платформы:**  
> Любая аннотация, полученная автоматическим или полуавтоматическим путем (`MODEL_PREDICTION`, `KEYPOINT_PROPAGATION`), является **предложением (гипотезой)** и имеет статус **неподтвержденной**.  
> Ни одно изображение с неподтвержденными аннотациями **не может** быть включено в версию датасета и **не может** использоваться для обучения следующих версий нейросети. Доступ в обучающую выборку разрешен исключительно после явного действия человека-верификатора (*Подтвердить* / *Изменить*).

---

## 2. Жизненный цикл и матрица состояний разметки

### 2.1. Жизненный цикл аннотации (`Annotation`)
Каждая ограничивающая рамка проходит через строгую машину состояний:

```
[Источник: KEYPOINT_PROPAGATION] ──┐
                                  ├──► [PENDING_REVIEW] ──► (Человек подтвердил) ──► [VERIFIED]
[Источник: MODEL_PREDICTION]     ──┘          │
                                              ├──► (Человек скорректировал) ──► [VERIFIED]
                                              │
                                              └──► (Человек отклонил)       ──► [REJECTED]

[Источник: MANUAL] ──────────────────────────────────────────────────────────► [VERIFIED]
```

* **`PENDING_REVIEW` (Ожидает проверки):** Начальный статус для любой рамки, полученной через алгоритмы LightGlue/SuperPoint/SIFT или инференс YOLO. В UI отображается пунктиром и предупреждающим цветом.
* **`VERIFIED` (Подтверждено):** Человек нажал «Подтвердить», скорректировал геометрию рамки или нарисовал ее вручную. Только такие рамки попадают в обучение.
* **`REJECTED` (Отклонено):** Человек счел предсказание ложным срабатыванием. Рамка физически удаляется или помечается как отклоненная и исключается из расчетов.

### 2.2. Жизненный цикл изображения (`Image`)
Статус кадра напрямую зависит от статуса находящихся на нем рамок:

* **`UNANNOTATED`:** На кадре нет ни одной рамки (ни ручной, ни автоматической).
* **`REQUIRES_REVIEW`:** На кадре есть хотя бы одна рамка со статусом `PENDING_REVIEW`. Кадр заблокирован для добавления в обучающую выборку.
* **`VERIFIED`:** Все объекты на кадре имеют статус `VERIFIED` (или кадр подтвержден человеком как фоновый/пустой — negative sample). Кадр готов к включению в датасет.
* **`REJECTED`:** Кадр признан оператором бракованным (размыт, испорчен, не относится к задаче).

---

## 3. Спецификация доменных сущностей

### 3.1. Контекст ядра и разметки (Core & Labeling Context)

#### `Project` (Проект)
Агрегат верхнего уровня, объединяющий конфигурацию классов, пул изображений, версии данных и модели.
* **Атрибуты:**
  * `id` *(UUID)* — уникальный идентификатор.
  * `name` *(String)* — наименование проекта.
  * `description` *(Text, опционально)* — описание задачи детекции.
  * `created_at` / `updated_at` *(Timestamp)*.

---

#### `AnnotationClass` (Класс объектов)
Справочник категорий объектов для распознавания.
* **Атрибуты:**
  * `id` *(UUID)* — уникальный идентификатор.
  * `project_id` *(UUID, FK $\to$ Project)* — ссылка на проект.
  * `name` *(String)* — имя класса (например, `crack`, `dent`).
  * `color_hex` *(String)* — цвет отображения в UI (`#22C55E`).
  * `index_id` *(Integer)* — порядковый индекс класса для YOLO ($0, 1, 2 \dots$).
* **Инварианты:** Уникальность пар `(project_id, name)` и `(project_id, index_id)`.

---

#### `Image` (Изображение)
Файл в хранилище и его текущее состояние в пайплайне проверки.
* **Атрибуты:**
  * `id` *(UUID)* — уникальный идентификатор.
  * `project_id` *(UUID, FK $\to$ Project)* — ссылка на проект.
  * `file_path` *(String)* — относительный путь к файлу на локальном диске (`projects/{id}/images/...`).
  * `file_name` *(String)* — имя загруженного файла.
  * `width` *(Integer)* — исходная ширина в пикселях.
  * `height` *(Integer)* — исходная высота в пикселях.
  * `source_type` *(Enum: `MANUAL_UPLOAD`, `STREAM_INGEST`, `DATASET_IMPORT`)* — канал поступления.
  * `stream_source_id` *(UUID, опционально, FK $\to$ StreamSource)* — ссылка на видеопоток (если кадр захвачен со стрима).
  * `status` *(Enum: `UNANNOTATED`, `REQUIRES_REVIEW`, `VERIFIED`, `REJECTED`)* — текущий статус валидации кадра.
  * `created_at` *(Timestamp)*.
* **Инвариант целостности:** Кадр не может получить статус `VERIFIED`, пока на нем существует хотя бы одна аннотация в статусе `PENDING_REVIEW`.

---

#### `Annotation` (Ограничивающая рамка / Bounding Box)
Единица разметки. Хранит координаты, источник создания и параметры верификации человеком.
* **Атрибуты:**
  * `id` *(UUID)* — уникальный идентификатор.
  * `image_id` *(UUID, FK $\to$ Image)* — связь с кадром.
  * `class_id` *(UUID, FK $\to$ AnnotationClass)* — ссылка на класс.
  * **Координаты (строго нормализованы $0.0 \dots 1.0$):**
    * `x_center` *(Float)* — центр по оси X.
    * `y_center` *(Float)* — центр по оси Y.
    * `width` *(Float)* — ширина бокса.
    * `height` *(Float)* — высота бокса.
  * **Происхождение (Provenance):**
    * `source` *(Enum)*:
      * `MANUAL` — создана человеком вручную через Canvas;
      * `KEYPOINT_PROPAGATION` — перенесена и сопоставлена по точкам (LightGlue/SuperPoint/SIFT);
      * `MODEL_PREDICTION` — найдена обученной моделью YOLO.
    * `confidence` *(Float, опционально)* — степень уверенности ($0.0 \dots 1.0$) для моделей.
    * `model_version_id` *(UUID, опционально, FK $\to$ ModelVersion)* — ссылка на модель, если рамка сгенерирована нейросетью.
    * `source_annotation_id` *(UUID, опционально, FK $\to$ Annotation)* — ссылка на бокс-донор, если использован перенос через ключевые точки.
  * **Аудит верификации человеком (Human-in-the-Loop):**
    * `verification_status` *(Enum)*:
      * `PENDING_REVIEW` — требует подтверждения (устанавливается по умолчанию для `KEYPOINT_PROPAGATION` и `MODEL_PREDICTION`);
      * `VERIFIED` — проверено и одобрено человеком (устанавливается по умолчанию для `MANUAL`);
      * `REJECTED` — отклонено человеком как ошибка алгоритма.
    * `verified_at` *(Timestamp, опционально)* — момент времени, когда человек подтвердил или изменил рамку.
* **Инварианты валидации:**
  * Если `source == MANUAL` $\implies$ `verification_status` ВСЕГДА равен `VERIFIED`, `confidence = 1.0`.
  * Если `source IN (KEYPOINT_PROPAGATION, MODEL_PREDICTION)` при создании $\implies$ `verification_status` ВСЕГДА равен `PENDING_REVIEW`.
  * Переход из `PENDING_REVIEW` в `VERIFIED` возможен только по явной команде пользователя (API-запрос подтверждения или редактирования).

---

### 3.2. Контекст версионирования датасета (Dataset & Augmentation Context)

#### `DatasetVersion` (Срез / Версия датасета)
Неизменяемый (Immutable) снимок проверенных данных, подготовленный для запуска обучения.
* **Атрибуты:**
  * `id` *(UUID)* — уникальный идентификатор версии.
  * `project_id` *(UUID, FK $\to$ Project)* — проект.
  * `version_number` *(Integer)* — номер версии (`1`, `2`, `3`...).
  * `name` *(String)* — имя версии (например, `v1-verified-core-50imgs`).
  * `status` *(Enum: `PREPARING`, `READY`, `FAILED`)* — статус генерации файлов на диске.
  * `train_count` *(Integer)* — число кадров в выборке Train.
  * `valid_count` *(Integer)* — число кадров в выборке Valid.
  * `test_count` *(Integer)* — число кадров в выборке Test.
  * `yaml_path` *(String)* — путь к итоговому `data.yaml`.
  * `created_at` *(Timestamp)*.
* **Инвариант генерации версии (Security Gate):**
  * В сборку `DatasetVersion` разрешено включать изображения **только** в статусе `Image.status == VERIFIED`.
  * Если среди кандидатов на включение находится изображение со статусом `REQUIRES_REVIEW` или хотя бы одна рамка с `verification_status == PENDING_REVIEW`, сборка версии аварийно прерывается с бизнес-ошибкой `UnverifiedDataException`.

---

#### `DatasetItem` (Связь кадра с версией)
Фиксирует состояние кадра и его боксов на момент создания среза.
* **Атрибуты:**
  * `id` *(UUID)*.
  * `dataset_version_id` *(UUID, FK $\to$ DatasetVersion)*.
  * `image_id` *(UUID, FK $\to$ Image)*.
  * `split` *(Enum: `TRAIN`, `VALID`, `TEST`)* — целевая выборка.
  * `snapshot_annotations` *(JSON)* — точная копия подтвержденных координат на момент фиксации версии.

---

#### `AugmentationConfig` (Параметры аугментации)
* **Атрибуты:**
  * `id` *(UUID)*.
  * `dataset_version_id` *(UUID, FK $\to$ DatasetVersion)*.
  * `resize_width` / `resize_height` *(Integer, default 640)*.
  * `horizontal_flip` *(Boolean)*.
  * `vertical_flip` *(Boolean)*.
  * `brightness_contrast_range` *(Float)*.
  * `mosaic_prob` *(Float)*.
  * `multiplier` *(Integer, default 3)* — кратность умножения обучающей выборки.

---

### 3.3. Контекст машинного обучения (Machine Learning Context)

#### `ModelVersion` (Обученная модель)
Артефакт, полученный в результате обучения на конкретной версии датасета.
* **Атрибуты:**
  * `id` *(UUID)*.
  * `project_id` *(UUID, FK $\to$ Project)*.
  * `dataset_version_id` *(UUID, FK $\to$ DatasetVersion)* — датасет, на котором модель училась.
  * `version_number` *(Integer)* — номер версии модели (`1`, `2`...).
  * `weights_path` *(String)* — путь к весам (`storage/models/v1/best.pt`).
  * **Метрики качества:** `mAP50`, `mAP50_95`, `precision`, `recall`.
  * `is_active_for_stream` *(Boolean)* — используется ли модель на живом потоке.
  * `created_at` *(Timestamp)*.

---

#### `TrainingJob` (Задача на обучение)
* **Атрибуты:**
  * `id` *(UUID)*.
  * `project_id` *(UUID)*.
  * `dataset_version_id` *(UUID)*.
  * `status` *(Enum: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`)*.
  * `epochs` *(Integer, default 50)*, `batch_size` *(Integer)*, `device` *(String)*.
  * `metrics_history` *(JSON)* — история обучения по эпохам.
  * `error_message` *(Text, опционально)*.
  * `started_at` / `finished_at` *(Timestamp)*.

---

#### `AutoLabelJob` (Задача авторазметки пула картинок)
Пакетный запуск обученной модели для формирования предложений по разметке.
* **Атрибуты:**
  * `id` *(UUID)*.
  * `model_version_id` *(UUID, FK $\to$ ModelVersion)* — модель, производящая детекцию.
  * `confidence_threshold` *(Float)* — порог уверенности (например, $0.50$).
  * `status` *(Enum: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`)*.
  * `total_images_processed` *(Integer)*.
  * `total_predictions_generated` *(Integer)*.
* **Бизнес-логика создания объектов:**
  Каждое предсказание, сгенерированное в рамках этой задачи, записывается в таблицу `annotations` со значениями:
  * `source = MODEL_PREDICTION`
  * `verification_status = PENDING_REVIEW`
  * А целевому изображению выставляется статус `Image.status = REQUIRES_REVIEW`.

---

### 3.4. Контекст потокового сэмплинга (Streaming Context)

#### `StreamSource` (Источник видеопотока)
Конфигурация источника реального времени для поиска пограничных случаев (Uncertainty Sampling).
* **Атрибуты:**
  * `id` *(UUID)*.
  * `project_id` *(UUID, FK $\to$ Project)*.
  * `name` *(String)* — название камеры/потока.
  * `source_url` *(String)* — RTSP-ссылка или индекс устройства.
  * `is_active` *(Boolean)* — признак активности фонового захвата.
  * **Окно неопределенности (Active Learning Filter):**
    * `min_uncertainty_conf` *(Float, default 0.70)*.
    * `max_uncertainty_conf` *(Float, default 0.90)*.
  * `cooldown_seconds` *(Integer, default 3)* — задержка между сохранениями дубликатов.
  * `captured_frames_count` *(Integer)*.
* **Бизнес-правило захвата кадра со стрима:**
  1. Если модель обнаруживает объект с уверенностью в диапазоне $[0.70, 0.90]$:
     * Кадр физически сохраняется на диск;
     * В БД создается `Image` со статусом `status = REQUIRES_REVIEW` и `source_type = STREAM_INGEST`;
     * Создаются предварительные `Annotation` с `source = MODEL_PREDICTION` и `verification_status = PENDING_REVIEW`;
     * Кадр попадает в приоритетную очередь ревьюеру-человеку.

---

## 4. Сводная матрица перехода состояний при действиях пользователя

| Действие пользователя | Исходное состояние аннотации | Конечное состояние аннотации | Результирующее состояние изображения (`Image`) |
| :--- | :--- | :--- | :--- |
| **Рисование рамки с нуля (`W`)** | *Не существует* | `source = MANUAL`<br>`verification_status = VERIFIED` | `VERIFIED` (если нет других неподтвержденных) |
| **Вставка через точки (`Ctrl+Shift+V`)** | *Не существует* | `source = KEYPOINT_PROPAGATION`<br>`verification_status = PENDING_REVIEW` | `REQUIRES_REVIEW` |
| **Запуск авторазметки моделью** | *Не существует* | `source = MODEL_PREDICTION`<br>`verification_status = PENDING_REVIEW` | `REQUIRES_REVIEW` |
| **Нажатие «Подтвердить» (`Approve`)** | `PENDING_REVIEW` | `verification_status = VERIFIED`<br>`verified_at = NOW()` | `VERIFIED` (если все остальные боксы кадра проверены) |
| **Корректировка геометрии бокса** | `PENDING_REVIEW` | `verification_status = VERIFIED`<br>`verified_at = NOW()` | `VERIFIED` (если все остальные боксы кадра проверены) |
| **Нажатие «Отклонить» (`Reject` / `Del`)** | `PENDING_REVIEW` | Удаляется из БД или `verification_status = REJECTED` | Пересчитывается по оставшимся боксам кадра |

---

## 5. Правила целостности на уровне Clean Architecture

1. **В слое `Domain`:**
   * Метод сущности `Annotation.verify()` переводит статус в `VERIFIED` и выставляет текущее время.
   * Метод сущности `Image.can_be_included_in_dataset()` возвращает `True` **только** если `self.status == ImageStatus.VERIFIED` и отсутствуют дочерние аннотации со статусом `PENDING_REVIEW`.

2. **В слое `Application (Use Cases)`:**
   * `CreateDatasetVersionUseCase` обязан содержать валидатор:
     ```text
     ЕСЛИ список_выбранных_изображений содержит хотя бы одно с status != VERIFIED:
         ВЫБРОСИТЬ ОШИБКУ: "Невозможно создать версию датасета: обнаружены неподтвержденные данные"
     ```
   * `PropagateKeypointsUseCase` создает боксы **исключительно** с флагом `PENDING_REVIEW`.
   * `AutoLabelImagesUseCase` создает боксы **исключительно** с флагом `PENDING_REVIEW`.

3. **В слое `Infrastructure`:**
   * Запрос на экспорт или подготовку обучающей выборки выполняет жесткую фильтрацию на уровне SQL:
     `WHERE annotations.verification_status = 'VERIFIED'`. Неверифицированные гипотезы физически исключаются из сборки тренировочных файлов.