# Docling Document Processing API

**Version:** 2.0.0  
**Base URL:** `https://docling.gai.co.id`

API untuk memproses dokumen (PDF, DOCX, PPTX, XLSX, HTML, CSV, Markdown, Image, dll.) menggunakan engine Docling — mengekstrak teks dan tabel dari dokumen.

---

## Daftar Isi

- [Autentikasi](#autentikasi)
- [Format Response](#format-response)
- [Endpoint: Health & Info](#endpoint-health--info)
  - [Root](#root)
  - [Health Check](#health-check)
- [Endpoint: Konversi Dokumen](#endpoint-konversi-dokumen)
  - [Convert](#convert)
  - [Convert and Chunk](#convert-and-chunk)
- [Endpoint: Konversi Teks (Tanpa File)](#endpoint-konversi-teks-tanpa-file)
  - [Convert Text](#convert-text)
  - [Chunk Text](#chunk-text)
- [Endpoint: Async Task (Untuk File Besar/Proses Lama)](#endpoint-async-task-untuk-file-besarproses-lama)
  - [Convert Async](#convert-async)
  - [Convert and Chunk Async](#convert-and-chunk-async)
  - [Poll Task Status](#poll-task-status)
  - [Get Task Result](#get-task-result)
  - [Cancel Task](#cancel-task)
  - [List Tasks](#list-tasks)
- [Endpoint: Resumable Upload](#endpoint-resumable-upload)
  - [Init Upload](#init-upload)
  - [Upload Chunk](#upload-chunk)
  - [Check Upload Status](#check-upload-status)
- [Format File yang Didukung](#format-file-yang-didukung)
- [Batasan & Limitasi](#batasan--limitasi)
- [Error Codes](#error-codes)
- [Contoh Penggunaan (cURL)](#contoh-penggunaan-curl)
- [Contoh Penggunaan (Python)](#contoh-penggunaan-python)

---

## Autentikasi

Semua endpoint API (kecuali `/` dan `/health`) **wajib** menyertakan Bearer Token pada header `Authorization`.

```
Authorization: Bearer <your_token>
```

Token diperoleh melalui SSO provider. Hubungi administrator untuk mendapatkan client credentials.

---

## Format Response

Semua endpoint mengembalikan response dalam format standar `ApiResponse`:

### Response Sukses

```json
{
  "status": 0,
  "data": { ... },
  "timestamp": "2025-01-01T00:00:00.000Z"
}
```

### Response Error

```json
{
  "status": 4,
  "error_message": "Deskripsi error",
  "error_type": "ERROR_TYPE",
  "timestamp": "2025-01-01T00:00:00.000Z"
}
```

| Field           | Type            | Keterangan                                      |
|-----------------|-----------------|-------------------------------------------------|
| `status`        | `integer`       | `0` = sukses, `4` = error                      |
| `data`          | `object/null`   | Data response (hanya ada jika sukses)           |
| `error_message` | `string/null`   | Pesan error (hanya ada jika error)              |
| `error_type`    | `string/null`   | Tipe/kode error                                 |
| `timestamp`     | `string`        | Timestamp UTC response                          |

---

## Endpoint: Health & Info

### Root

Informasi umum tentang aplikasi.

```
GET /
```

**Autentikasi:** Tidak diperlukan

**Response:**

```json
{
  "status": 0,
  "data": {
    "app": "Docling Document Processing API",
    "environment": "prod",
    "debug": false,
    "version": "2.0.0",
    "status": "running",
    "focus": "text_and_tables"
  }
}
```

---

### Health Check

Memeriksa status kesehatan layanan.

```
GET /health
```

**Autentikasi:** Tidak diperlukan

**Response:**

```json
{
  "status": 0,
  "data": {
    "status": "healthy",
    "timestamp": 1735689600.0,
    "converter_status": "healthy",
    "redis_status": "healthy",
    "storage_status": "healthy",
    "task_worker_status": "running",
    "environment": "prod"
  }
}
```

| Field                  | Keterangan                                                  |
|------------------------|-------------------------------------------------------------|
| `status`               | `"healthy"` atau `"unhealthy"`                              |
| `converter_status`     | Status engine Docling (`"healthy"`/`"unhealthy"`)           |
| `redis_status`         | Status koneksi Redis (`"healthy"`/`"unavailable"`)          |
| `storage_status`       | Status object storage/MinIO (`"healthy"`/`"unavailable"`)   |
| `task_worker_status`   | Status background worker (`"running"`/`"stopped"`)          |

> **Catatan:** Response `503` dikembalikan bila salah satu komponen tidak sehat (`status: "unhealthy"`, `error_type: "UNHEALTHY"`).

---

## Endpoint: Konversi Dokumen

### Convert

Mengkonversi dokumen menjadi teks, markdown, atau HTML.

```
POST /api/v1/convert
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `multipart/form-data`

#### Parameter

| Field                    | Type     | Required | Default    | Keterangan                                                |
|--------------------------|----------|----------|------------|-----------------------------------------------------------||
| `file`                   | `file`   | Ya*      | -          | File dokumen yang akan diproses                           |
| `upload_id`              | `string` | Ya*      | -          | ID dari sesi upload sebelumnya (alternatif dari `file`)   |
| `enable_ocr`             | `string` | Tidak    | `"false"`  | Aktifkan OCR untuk dokumen scan/gambar (`"true"`/`"false"`) |
| `output_type`            | `string` | Tidak    | `markdown` | Format output: `markdown`, `plaintext`, `html`            |
| `use_stream`             | `boolean`| Tidak    | `null`     | Paksa streaming (`true`) atau file-based (`false`). Auto jika tidak diisi |
| `generate_picture_images`| `string` | Tidak    | `"false"`  | Ekstrak dan embed gambar dari PDF (`"true"`/`"false"`)    |
| `from_page`              | `integer`| Tidak    | `null`     | Halaman awal (1-based, inklusif)                          |
| `to_page`                | `integer`| Tidak    | `null`     | Halaman akhir (1-based, inklusif)                         |

> \* Salah satu dari `file` atau `upload_id` harus diisi.

> **Page Range:** Gunakan `from_page` dan `to_page` untuk mengkonversi halaman tertentu saja (1-based, inklusif). Jika hanya salah satu diisi, sisi yang kosong otomatis default ke halaman pertama / terakhir. Contoh: `from_page=3&to_page=7` hanya mengkonversi halaman 3–7.

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "content": "# Judul Dokumen\n\nIsi dokumen dalam format markdown...",
    "processing_time": 3.45,
    "streaming_used": true,
    "metadata": {
      "page_count": 10,
      "file_type": "pdf"
    }
  }
}
```

| Field             | Type      | Keterangan                                  |
|-------------------|-----------|---------------------------------------------|
| `content`         | `string`  | Hasil konversi dokumen                      |
| `processing_time` | `float`   | Waktu pemrosesan dalam detik                |
| `streaming_used`  | `boolean` | Apakah menggunakan streaming conversion     |
| `metadata`        | `object`  | Metadata dokumen (jumlah halaman, tipe file) |

---

### Convert and Chunk

Mengkonversi dokumen lalu memecahnya menjadi chunks yang cocok untuk LLM/RAG.

```
POST /api/v1/convert_n_chunk
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `multipart/form-data`

#### Parameter

| Field                    | Type      | Required | Default    | Keterangan                                                    |
|--------------------------|-----------|----------|------------|---------------------------------------------------------------||
| `file`                   | `file`    | Ya*      | -          | File dokumen yang akan diproses                               |
| `upload_id`              | `string`  | Ya*      | -          | ID dari sesi upload sebelumnya (alternatif dari `file`)       |
| `enable_ocr`             | `string`  | Tidak    | `"false"`  | Aktifkan OCR (`"true"`/`"false"`)                              |
| `ocr_langs`              | `string`  | Tidak    | `"id"`     | Bahasa OCR, comma-separated (contoh: `"id,en"`)               |
| `max_tokens`             | `integer` | Tidak    | `512`      | Jumlah token maksimum per chunk                               |
| `output_type`            | `string`  | Tidak    | `markdown` | Format output: `markdown`, `plaintext`, `html`                |
| `chunk_type`             | `string`  | Tidak    | `hybrid`   | Strategi chunking: `hybrid`, `hierarchical`, `page`           |
| `use_stream`             | `boolean` | Tidak    | `null`     | Paksa streaming (`true`) atau file-based (`false`). Auto      |
| `generate_picture_images`| `string`  | Tidak    | `"false"`  | Ekstrak dan embed gambar dari PDF (`"true"`/`"false"`)        |
| `from_page`              | `integer` | Tidak    | `null`     | Halaman awal (1-based, inklusif)                              |
| `to_page`                | `integer` | Tidak    | `null`     | Halaman akhir (1-based, inklusif)                             |

> \* Salah satu dari `file` atau `upload_id` harus diisi.

> **Page Range:** Gunakan `from_page` dan `to_page` untuk mengkonversi halaman tertentu saja. Lihat penjelasan di endpoint [Convert](#convert).

#### Chunk Types

| Type           | Keterangan                                                              |
|----------------|-------------------------------------------------------------------------|
| `hybrid`       | Chunking berbasis token dengan konteks hierarchical (direkomendasikan)  |
| `hierarchical` | Chunking berdasarkan struktur heading dokumen                           |
| `page`         | Chunking per halaman dokumen                                            |

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "conversion": {
      "content": "# Judul Dokumen\n\nIsi lengkap dokumen...",
      "metadata": {
        "page_count": 10,
        "file_type": "pdf"
      }
    },
    "chunks": [
      {
        "chunk_id": 0,
        "enriched_text": "Teks chunk dengan konteks...",
        "token_count": 256,
        "content": "Teks chunk dengan konteks..."
      },
      {
        "chunk_id": 1,
        "enriched_text": "Teks chunk berikutnya...",
        "token_count": 312,
        "content": "Teks chunk berikutnya..."
      }
    ],
    "total_chunks": 15,
    "processing_time": 5.78,
    "streaming_used": true
  }
}
```

| Field                   | Type       | Keterangan                                     |
|-------------------------|------------|------------------------------------------------|
| `conversion.content`    | `string`   | Hasil konversi dokumen lengkap                 |
| `conversion.metadata`   | `object`   | Metadata dokumen                               |
| `chunks`                | `array`    | Daftar chunks hasil pemecahan                  |
| `chunks[].chunk_id`     | `integer`  | ID chunk (dimulai dari 0)                      |
| `chunks[].enriched_text`| `string`   | Teks chunk dengan konteks/heading              |
| `chunks[].token_count`  | `integer`  | Jumlah token dalam chunk                       |
| `chunks[].content`      | `string`   | Sama dengan `enriched_text`                    |
| `total_chunks`          | `integer`  | Total jumlah chunks                            |
| `processing_time`       | `float`    | Waktu pemrosesan total dalam detik             |
| `streaming_used`        | `boolean`  | Apakah menggunakan streaming conversion        |

---

## Endpoint: Konversi Teks (Tanpa File)

Endpoint ini menerima konten teks/markdown langsung dalam JSON body — **tanpa perlu upload file fisik**. Cocok untuk kasus dimana konten sudah tersimpan di database atau sumber lain.

### Convert Text

Mengkonversi konten teks/markdown langsung tanpa upload file.

```
POST /api/v1/convert_text
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `application/json`

#### Request Body

```json
{
  "content": "# Judul Dokumen\n\nIsi dokumen dalam format markdown...",
  "filename": "document.md",
  "output_type": "markdown"
}
```

| Field                    | Type      | Required | Default         | Keterangan                                                 |
|--------------------------|-----------|----------|-----------------|-----------------------------------------------------------||
| `content`                | `string`  | Ya       | -               | Konten teks/markdown yang akan dikonversi                   |
| `filename`               | `string`  | Tidak    | `"document.md"` | Nama file virtual (digunakan untuk deteksi format)          |
| `output_type`            | `string`  | Tidak    | `"markdown"`    | Format output: `markdown`, `plaintext`, `html`              |
| `generate_picture_images`| `boolean` | Tidak    | `false`         | Ekstrak dan embed gambar dari PDF                           |
| `from_page`              | `integer` | Tidak    | `null`          | Halaman awal (1-based, inklusif)                            |
| `to_page`                | `integer` | Tidak    | `null`          | Halaman akhir (1-based, inklusif)                           |

> **Catatan:** Ekstensi `filename` digunakan Docling untuk mendeteksi format input. Gunakan `.md` untuk markdown, `.html` untuk HTML, `.csv` untuk CSV, dll.

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "content": "# Judul Dokumen\n\nIsi dokumen yang sudah dikonversi...",
    "processing_time": 0.85,
    "metadata": {
      "page_count": null,
      "file_type": "md"
    }
  }
}
```

| Field             | Type      | Keterangan                                   |
|-------------------|-----------|----------------------------------------------|
| `content`         | `string`  | Hasil konversi dokumen                       |
| `processing_time` | `float`   | Waktu pemrosesan dalam detik                 |
| `metadata`        | `object`  | Metadata dokumen                             |

---

### Chunk Text

Mengkonversi dan memecah konten teks/markdown menjadi chunks — tanpa upload file. Sangat berguna untuk konten yang diambil dari database untuk diproses sebagai embedding RAG/LLM.

```
POST /api/v1/chunk_text
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `application/json`

#### Request Body

```json
{
  "content": "# Judul\n\nParagraf pertama...\n\n## Sub Heading\n\nParagraf kedua...",
  "filename": "document.md",
  "max_tokens": 512,
  "chunk_type": "hybrid",
  "output_type": "markdown"
}
```

| Field                    | Type      | Required | Default         | Keterangan                                                 |
|--------------------------|-----------|----------|-----------------|-----------------------------------------------------------||
| `content`                | `string`  | Ya       | -               | Konten teks/markdown yang akan di-chunk                     |
| `filename`               | `string`  | Tidak    | `"document.md"` | Nama file virtual (deteksi format)                          |
| `max_tokens`             | `integer` | Tidak    | `512`           | Jumlah token maksimum per chunk                             |
| `chunk_type`             | `string`  | Tidak    | `"hybrid"`      | Strategi chunking: `hybrid`, `hierarchical`, `page`         |
| `output_type`            | `string`  | Tidak    | `"markdown"`    | Format output: `markdown`, `plaintext`, `html`              |
| `generate_picture_images`| `boolean` | Tidak    | `false`         | Ekstrak dan embed gambar dari PDF                           |
| `from_page`              | `integer` | Tidak    | `null`          | Halaman awal (1-based, inklusif)                            |
| `to_page`                | `integer` | Tidak    | `null`          | Halaman akhir (1-based, inklusif)                           |

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "conversion": {
      "content": "# Judul\n\nIsi lengkap dokumen...",
      "metadata": {
        "page_count": null,
        "file_type": "md"
      }
    },
    "chunks": [
      {
        "chunk_id": 0,
        "enriched_text": "Teks chunk dengan konteks...",
        "token_count": 256,
        "content": "Teks chunk dengan konteks..."
      },
      {
        "chunk_id": 1,
        "enriched_text": "Teks chunk berikutnya...",
        "token_count": 312,
        "content": "Teks chunk berikutnya..."
      }
    ],
    "total_chunks": 8,
    "processing_time": 1.23
  }
}
```

| Field                        | Type       | Keterangan                                     |
|------------------------------|------------|------------------------------------------------|
| `conversion.content`         | `string`   | Hasil konversi konten lengkap                  |
| `conversion.metadata`        | `object`   | Metadata konten                                |
| `chunks`                     | `array`    | Daftar chunks hasil pemecahan                  |
| `chunks[].chunk_id`          | `integer`  | ID chunk (dimulai dari 0)                      |
| `chunks[].enriched_text`     | `string`   | Teks chunk dengan konteks/heading              |
| `chunks[].token_count`       | `integer`  | Jumlah token dalam chunk                       |
| `chunks[].content`           | `string`   | Sama dengan `enriched_text`                    |
| `total_chunks`               | `integer`  | Total jumlah chunks                            |
| `processing_time`            | `float`    | Waktu pemrosesan total dalam detik             |

---

## Endpoint: Async Task (Untuk File Besar/Proses Lama)

> **Gunakan endpoint ini untuk dokumen yang membutuhkan waktu pemrosesan lama (30 menit atau lebih).** Endpoint sync (`/convert`, `/convert_n_chunk`) akan timeout jika proses terlalu lama. Endpoint async menggunakan pola **submit-and-poll** dan mendukung **webhook callback**: submit task, lalu poll status atau tunggu notifikasi callback.

### Alur Async Task

```
1. POST /api/v1/convert_async            → Submit task + callback_url opsional (HTTP 202)
2. GET  /api/v1/tasks/{task_id}          → Poll status (ulangi sampai status terminal)
3. GET  /api/v1/tasks/{task_id}/result   → Ambil hasil saat status = "completed"
   (atau tunggu webhook callback ke callback_url)
```

> **Retensi hasil:** hasil proses disimpan di object storage (MinIO) selama **7 hari**; status task di Redis ikut kadaluarsa setelah 7 hari. Setelah masa retensi, hasil tidak dapat diambil lagi.

> **Timeout:** task yang menunggu di antrean > 12 jam berstatus `expired`; task yang diproses melebihi batas waktu (default 90 menit, per-request maksimum 3 jam) berstatus `timeout`.

---

### Convert Async

Submit task konversi dokumen secara asynchronous. Response langsung dikembalikan (HTTP 202) tanpa menunggu proses selesai.

```
POST /api/v1/convert_async
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `multipart/form-data`

#### Parameter

| Field                    | Type     | Required | Default    | Keterangan                                                |
|--------------------------|----------|----------|------------|-----------------------------------------------------------||
| `file`                   | `file`   | Ya       | -          | File dokumen yang akan diproses                           |
| `enable_ocr`             | `string` | Tidak    | `"false"`  | Aktifkan OCR untuk dokumen scan/gambar (`"true"`/`"false"`) |
| `output_type`            | `string` | Tidak    | `markdown` | Format output: `markdown`, `plaintext`, `html`            |
| `generate_picture_images`| `string` | Tidak    | `"false"`  | Ekstrak dan embed gambar dari PDF (`"true"`/`"false"`)    |
| `from_page`              | `integer`| Tidak    | `null`     | Halaman awal (1-based, inklusif)                          |
| `to_page`                | `integer`| Tidak    | `null`     | Halaman akhir (1-based, inklusif)                          |
| `callback_url`           | `string` | Tidak    | `null`     | Webhook URL (http/https absolut) untuk notifikasi saat task mencapai status terminal |
| `timeout_seconds`        | `integer`| Tidak    | `null`     | Override batas waktu pemrosesan per-request (maksimum 10800 detik = 3 jam) |

#### Response (HTTP 202 Accepted)

```json
{
  "status": 0,
  "data": {
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "pending",
    "message": "Task submitted successfully. Poll the status URL or wait for the callback.",
    "poll_url": "/api/v1/tasks/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "result_url": "/api/v1/tasks/a1b2c3d4-e5f6-7890-abcd-ef1234567890/result",
    "callback_url": "https://your-app.example.com/webhook"
  }
}
```

| Field          | Type     | Keterangan                                       |
|----------------|----------|--------------------------------------------------|
| `task_id`      | `string` | ID unik task (gunakan untuk polling)             |
| `status`       | `string` | Status awal: `"pending"`                         |
| `message`      | `string` | Pesan konfirmasi                                 |
| `poll_url`     | `string` | URL untuk poll status task                        |
| `result_url`   | `string` | URL untuk mengambil hasil setelah `completed`      |
| `callback_url` | `string` | Webhook URL (echo) — hanya jika dikirim saat submit |

#### Webhook Callback (Opsional)

Jika `callback_url` dikirim saat submit, server akan mengirim HTTP POST berisi JSON saat task mencapai status terminal (`completed`/`failed`/`cancelled`/`expired`/`timeout`).

**Header:**

```
Content-Type: application/json
X-Task-Id: <task_id>
X-Signature: sha256=<HMAC-SHA256 dari body mentah menggunakan SECRET_KEY>
```

**Body:**

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "endpoint": "convert",
  "created_at": 1735689600.0,
  "started_at": 1735689610.0,
  "completed_at": 1735690200.0,
  "processing_time": 590.0,
  "result_summary": { "size_bytes": 123456, "page_count": 150, "output_type": "markdown" },
  "result_url": "https://minio.../presigned-url",
  "error": null
}
```

> Callback dikirim dengan retry (maksimum 3 kali, backoff eksponensial). Callback dapat terkirim lebih dari sekali — gunakan `task_id` sebagai idempotency key.

---

### Convert and Chunk Async

Submit task konversi + chunking dokumen secara asynchronous.

```
POST /api/v1/convert_n_chunk_async
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `multipart/form-data`

#### Parameter

| Field                    | Type      | Required | Default    | Keterangan                                                    |
|--------------------------|-----------|----------|------------|---------------------------------------------------------------||
| `file`                   | `file`    | Ya       | -          | File dokumen yang akan diproses                               |
| `enable_ocr`             | `string`  | Tidak    | `"false"`  | Aktifkan OCR (`"true"`/`"false"`)                              |
| `ocr_langs`              | `string`  | Tidak    | `"id"`     | Bahasa OCR, comma-separated (contoh: `"id,en"`)               |
| `max_tokens`             | `integer` | Tidak    | `512`      | Jumlah token maksimum per chunk                               |
| `output_type`            | `string`  | Tidak    | `markdown` | Format output: `markdown`, `plaintext`, `html`                |
| `chunk_type`             | `string`  | Tidak    | `hybrid`   | Strategi chunking: `hybrid`, `hierarchical`, `page`           |
| `generate_picture_images`| `string`  | Tidak    | `"false"`  | Ekstrak dan embed gambar dari PDF (`"true"`/`"false"`)        |
| `from_page`              | `integer` | Tidak    | `null`     | Halaman awal (1-based, inklusif)                              |
| `to_page`                | `integer` | Tidak    | `null`     | Halaman akhir (1-based, inklusif)                             |
| `callback_url`           | `string`  | Tidak    | `null`     | Webhook URL (http/https absolut) untuk notifikasi status terminal |
| `timeout_seconds`        | `integer` | Tidak    | `null`     | Override batas waktu pemrosesan per-request (maksimum 10800 detik) |

#### Response (HTTP 202 Accepted)

```json
{
  "status": 0,
  "data": {
    "task_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "status": "pending",
    "message": "Task submitted successfully. Poll the status URL or wait for the callback.",
    "poll_url": "/api/v1/tasks/b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "result_url": "/api/v1/tasks/b2c3d4e5-f6a7-8901-bcde-f12345678901/result"
  }
}
```

---

### Poll Task Status

Memeriksa status task async (dan ringkasan hasil bila selesai). **Ulangi request ini** sampai status berubah menjadi salah satu status terminal (`completed`, `failed`, `cancelled`, `expired`, `timeout`). Untuk mengambil hasil lengkap, gunakan `result_url` (presigned) atau endpoint [Get Task Result](#get-task-result).

```
GET /api/v1/tasks/{task_id}
```

**Autentikasi:** Diperlukan (Bearer Token)

#### Path Parameter

| Parameter  | Type     | Keterangan                         |
|------------|----------|------------------------------------|
| `task_id`  | `string` | ID task dari response submit       |

#### Task Status Lifecycle

```
pending → processing → completed
                    → failed
                    → timeout       (melebihi batas waktu proses)
pending → cancelled
pending → expired             (menunggu di antrean > 12 jam)
```

| Status        | Keterangan                                          |
|---------------|-----------------------------------------------------|
| `pending`     | Task antri, belum diproses                          |
| `processing`  | Task sedang diproses oleh worker                    |
| `completed`   | Task selesai; hasil tersedia via `result_url`       |
| `failed`      | Task gagal; error tersedia di field `error`         |
| `cancelled`   | Task dibatalkan (hanya bisa saat masih `pending`)   |
| `expired`     | Task kadaluarsa karena terlalu lama di antrean      |
| `timeout`     | Task melebihi batas waktu pemrosesan                |

#### Response - Task Masih Diproses

```json
{
  "status": 0,
  "data": {
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "processing",
    "endpoint": "convert",
    "created_at": 1735689600.0,
    "started_at": 1735689610.0,
    "completed_at": null,
    "processing_time": null,
    "queue_expires_at": 1735732800.0,
    "processing_deadline": 1735695010.0,
    "result_summary": null,
    "poll_after": 5
  }
}
```

| Field                 | Keterangan                                                        |
|-----------------------|-------------------------------------------------------------------|
| `queue_expires_at`    | Batas waktu tunggu di antrean (epoch seconds)                     |
| `processing_deadline` | Batas waktu proses task ini (epoch seconds)                       |
| `poll_after`          | Saran interval polling berikutnya (detik); hanya saat in-flight   |

#### Response - Task Selesai

Hasil **tidak lagi dikirim inline** (bisa puluhan MB untuk dokumen besar). Gunakan `result_url` untuk mengambil artifact JSON hasil konversi.

```json
{
  "status": 0,
  "data": {
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "completed",
    "endpoint": "convert",
    "created_at": 1735689600.0,
    "started_at": 1735689610.0,
    "completed_at": 1735690200.0,
    "processing_time": 590.0,
    "queue_expires_at": 1735732800.0,
    "processing_deadline": 1735695010.0,
    "result_summary": {
      "size_bytes": 123456,
      "page_count": 150,
      "output_type": "markdown",
      "processing_time": 590.0
    },
    "result_url": "https://minio.example.com/docling/results/.../result.json?X-Amz-..."
  }
}
```

| Field            | Keterangan                                                              |
|------------------|-------------------------------------------------------------------------|
| `result_summary` | Ringkasan hasil (ukuran, jumlah halaman, jumlah chunk bila ada)         |
| `result_url`     | URL presigned (berlaku sementara) atau path `/api/v1/tasks/{id}/result` |

#### Response - Task Gagal

```json
{
  "status": 0,
  "data": {
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "failed",
    "endpoint": "convert",
    "created_at": 1735689600.0,
    "started_at": 1735689610.0,
    "completed_at": 1735689650.0,
    "processing_time": 40.0,
    "error": "Document conversion failed: unsupported format"
  }
}
```

---

### Get Task Result

Mengambil artifact JSON hasil proses task yang sudah `completed`. Hasil disimpan di object storage dengan retensi **7 hari**.

```
GET /api/v1/tasks/{task_id}/result
```

**Autentikasi:** Diperlukan (Bearer Token)

#### Response

- `200` — body JSON hasil konversi (sama seperti format pada endpoint sync, mis. field `content` dan `metadata`)
- `404` — task tidak ditemukan / artifact tidak tersedia
- `409` — task belum selesai (status masih `pending`/`processing`)
- `410` — artifact sudah kadaluarsa (masa retensi 7 hari terlewati)

---

### Cancel Task

Membatalkan task yang masih `pending` di antrean.

```
DELETE /api/v1/tasks/{task_id}
```

**Autentikasi:** Diperlukan (Bearer Token)

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "cancelled"
  }
}
```

> `404` dikembalikan bila task tidak ditemukan atau tidak dapat dibatalkan (sudah `processing`/terminal).

---

### List Tasks

Menampilkan daftar task async terbaru (diurutkan dari yang terbaru).

```
GET /api/v1/tasks
```

**Autentikasi:** Diperlukan (Bearer Token)

#### Query Parameters

| Parameter | Type      | Default | Keterangan                         |
|-----------|-----------|---------|-------------------------------------|
| `limit`   | `integer` | `20`    | Jumlah maksimum task yang ditampilkan |
| `offset`  | `integer` | `0`     | Offset untuk pagination              |

#### Response

```json
{
  "status": 0,
  "data": {
    "tasks": [
      {
        "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "status": "completed",
        "endpoint": "convert",
        "created_at": 1735689600.0,
        "started_at": 1735689610.0,
        "completed_at": 1735690200.0,
        "processing_time": 590.0
      },
      {
        "task_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "status": "pending",
        "endpoint": "convert_n_chunk",
        "created_at": 1735689500.0,
        "started_at": null,
        "completed_at": null,
        "processing_time": null
      }
    ],
    "count": 2
  }
}
```

> **Catatan:** Status dan hasil task otomatis dihapus setelah **7 hari** (`TASK_RESULT_TTL`), sinkron dengan lifecycle rule pada object storage (MinIO) untuk prefix `results/`.

---

## Endpoint: Resumable Upload

Untuk file besar (hingga 200MB), gunakan mekanisme resumable upload. Upload file secara bertahap, lalu gunakan `upload_id` untuk konversi.

### Alur Resumable Upload

```
1. POST /api/v1/upload/init        → Dapatkan upload_id
2. PUT  /api/v1/upload/{upload_id} → Kirim chunk data (bisa berulang)
3. GET  /api/v1/upload/{upload_id} → Cek status upload (opsional)
4. POST /api/v1/convert            → Gunakan upload_id untuk konversi
   (atau POST /api/v1/convert_n_chunk)
```

---

### Init Upload

Memulai sesi upload baru dan mendapatkan `upload_id`.

```
POST /api/v1/upload/init
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `multipart/form-data`

#### Parameter

| Field       | Type      | Required | Default | Keterangan                          |
|-------------|-----------|----------|---------|-------------------------------------|
| `filename`  | `string`  | Ya       | -       | Nama file asli                      |
| `total_size`| `integer` | Ya       | -       | Ukuran total file dalam bytes (min: 1) |
| `mime_type` | `string`  | Tidak    | `null`  | MIME type file (contoh: `application/pdf`) |

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "upload_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "dokumen_besar.pdf",
    "total_size": 104857600,
    "received_size": 0,
    "status": "in_progress",
    "progress": 0.0,
    "message": "Upload session initialized. Send chunks via PUT /upload/{upload_id}"
  }
}
```

---

### Upload Chunk

Mengirim chunk data file ke sesi upload yang sudah diinisiasi.

```
PUT /api/v1/upload/{upload_id}
```

**Autentikasi:** Diperlukan (Bearer Token)  
**Content-Type:** `application/octet-stream`

#### Path Parameter

| Parameter    | Type     | Keterangan                    |
|--------------|----------|-------------------------------|
| `upload_id`  | `string` | ID sesi upload dari init      |

#### Header (Opsional)

```
Content-Range: bytes {start}-{end}/{total}
```

Contoh: `Content-Range: bytes 0-999999/10000000`

Gunakan header `Content-Range` jika ingin resume dari offset tertentu. Untuk upload sequential sederhana, header ini bisa diabaikan.

#### Body

Raw binary data (chunk file).

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "upload_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "received_size": 1000000,
    "total_size": 10000000,
    "progress": 10.0,
    "status": "in_progress",
    "object_key": null
  }
}
```

Ketika semua bytes sudah diterima (`progress: 100.0`), file dipindahkan ke object storage, status berubah menjadi `"completed"`, dan `object_key` terisi.

| Field        | Keterangan                                                    |
|--------------|---------------------------------------------------------------|
| `status`     | `"in_progress"`, `"completed"`, atau `"failed"`               |
| `progress`   | Persentase upload (0.0 - 100.0)                               |
| `object_key` | Object storage key (hanya tersedia jika status = `"completed"`) |

> Sesi upload disimpan di Redis dengan TTL 2 jam dan terikat ke user yang menginisiasinya.

---

### Check Upload Status

Memeriksa status dan progress sesi upload.

```
GET /api/v1/upload/{upload_id}
```

**Autentikasi:** Diperlukan (Bearer Token)

#### Path Parameter

| Parameter    | Type     | Keterangan               |
|--------------|----------|--------------------------|
| `upload_id`  | `string` | ID sesi upload           |

#### Response Sukses

```json
{
  "status": 0,
  "data": {
    "upload_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "filename": "dokumen_besar.pdf",
    "received_size": 5000000,
    "total_size": 10000000,
    "progress": 50.0,
    "status": "in_progress",
    "created_at": 1735689600.0,
    "updated_at": 1735689650.0
  }
}
```

---

## Format File yang Didukung

| Format         | Ekstensi            |
|----------------|---------------------|
| PDF            | `.pdf`              |
| Image          | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.gif` |
| Word           | `.docx`             |
| PowerPoint     | `.pptx`             |
| Excel          | `.xlsx`             |
| HTML           | `.html`, `.htm`     |
| CSV            | `.csv`              |
| Markdown       | `.md`               |
| AsciiDoc       | `.adoc`             |

---

## Batasan & Limitasi

| Parameter                | Nilai          | Keterangan                                      |
|--------------------------|----------------|-------------------------------------------------|
| Max file size            | **200 MB**     | Ukuran maksimum file yang dapat diupload        |
| Stream threshold         | **50 MB**      | File ≤ 50MB otomatis menggunakan streaming      |
| Default max tokens/chunk | **512**        | Token maksimum per chunk (bisa di-override)     |
| Thread pool size         | **4**          | Jumlah worker untuk proses paralel              |
| Max async task queue     | **100**        | Jumlah task async yang bisa mengantri           |
| Queue timeout            | **12 jam**     | Task yang menunggu lebih lama berstatus `expired` |
| Processing timeout       | **90 menit**   | Batas waktu proses default per task (override hingga 3 jam) |
| Task/result TTL          | **7 hari**     | Status task dan artifact hasil dihapus otomatis  |
| Upload session TTL       | **2 jam**      | Sesi resumable upload kadaluarsa otomatis        |

---

## Error Codes

### HTTP Status Codes

| Code | Keterangan                                              |
|------|---------------------------------------------------------|
| 200  | Sukses                                                  |
| 202  | Accepted (task async berhasil disubmit)                 |
| 400  | Bad Request (parameter tidak valid, file kosong, dll.)  |
| 401  | Unauthorized (token tidak ada/invalid/expired)           |
| 404  | Not Found (task/upload session tidak ditemukan)          |
| 409  | Conflict (task belum selesai / sesi upload belum completed) |
| 410  | Gone (artifact hasil sudah kadaluarsa - retensi 7 hari)  |
| 413  | Payload Too Large (file melebihi batas 200MB)           |
| 422  | Unprocessable Entity (validasi request gagal)           |
| 429  | Too Many Requests (server sibuk memproses dokumen lain)  |
| 500  | Internal Server Error                                   |
| 503  | Service Unavailable (SSO/Redis/queue/storage down)      |

### Application Error Types

| `error_type`       | Keterangan                                |
|--------------------|-------------------------------------------|
| `INTERNAL_ERROR`   | Error internal server yang tidak terduga  |
| `VALIDATION_ERROR` | Validasi input gagal                      |
| `UNHEALTHY`        | Salah satu komponen health check tidak sehat |
| `HTTP_<code>`      | Error HTTP yang dibungkus response envelope |

---

## Contoh Penggunaan (cURL)

### 1. Konversi Dokumen Sederhana

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/dokumen.pdf" \
  -F "enable_ocr=false" \
  -F "output_type=markdown"
```

### 2. Konversi dengan OCR

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/scanned_doc.pdf" \
  -F "enable_ocr=true" \
  -F "output_type=markdown"
```

### 3. Konversi Halaman Tertentu (Page Range)

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/dokumen.pdf" \
  -F "output_type=markdown" \
  -F "from_page=3" \
  -F "to_page=7"
```

> Hanya halaman 3 sampai 7 yang akan dikonversi (1-based, inklusif).

### 4. Konversi dengan Ekstraksi Gambar (PDF)

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/dokumen_dengan_gambar.pdf" \
  -F "enable_ocr=false" \
  -F "output_type=markdown" \
  -F "generate_picture_images=true"
```

### 5. Konversi dan Chunking

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert_n_chunk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/dokumen.pdf" \
  -F "enable_ocr=false" \
  -F "max_tokens=1024" \
  -F "output_type=markdown" \
  -F "chunk_type=hybrid"
```

### 6. Konversi dan Chunking Halaman Tertentu (Page Range)

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert_n_chunk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/dokumen.pdf" \
  -F "max_tokens=1024" \
  -F "chunk_type=hybrid" \
  -F "from_page=1" \
  -F "to_page=10"
```

### 7. Resumable Upload (File Besar)

```bash
# Step 1: Init upload
UPLOAD_ID=$(curl -s -X POST "https://docling.gai.co.id/api/v1/upload/init" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "filename=big_document.pdf" \
  -F "total_size=104857600" | jq -r '.data.upload_id')

# Step 2: Upload file (single chunk, for file ≤ total_size)
curl -X PUT "https://docling.gai.co.id/api/v1/upload/${UPLOAD_ID}" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @/path/to/big_document.pdf

# Step 3: Check status (opsional)
curl -X GET "https://docling.gai.co.id/api/v1/upload/${UPLOAD_ID}" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Step 4: Convert menggunakan upload_id
curl -X POST "https://docling.gai.co.id/api/v1/convert" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "upload_id=${UPLOAD_ID}" \
  -F "enable_ocr=false" \
  -F "output_type=markdown"
```

### 8. Konversi Output HTML

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/dokumen.docx" \
  -F "output_type=html"
```

### 9. Chunking dengan Strategi Hierarchical

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert_n_chunk" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/dokumen.pdf" \
  -F "max_tokens=512" \
  -F "chunk_type=hierarchical"
```

### 10. Konversi Teks/Markdown Langsung (Tanpa File)

```bash
curl -X POST "https://docling.gai.co.id/api/v1/convert_text" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# Judul Dokumen\n\nIni adalah isi dokumen dalam format markdown.",
    "filename": "document.md",
    "output_type": "markdown"
  }'
```

### 11. Chunk Teks/Markdown dari Database (Tanpa File)

```bash
curl -X POST "https://docling.gai.co.id/api/v1/chunk_text" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# Judul\n\nParagraf pertama...\n\n## Sub Heading\n\nParagraf kedua...",
    "filename": "document.md",
    "max_tokens": 512,
    "chunk_type": "hybrid"
  }'
```

### 12. Konversi Asynchronous (File Besar/Proses Lama)

```bash
# Step 1: Submit task (opsional: sertakan callback_url untuk notifikasi otomatis)
TASK_ID=$(curl -s -X POST "https://docling.gai.co.id/api/v1/convert_async" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/large_document.pdf" \
  -F "enable_ocr=true" \
  -F "output_type=markdown" \
  -F "callback_url=https://your-app.example.com/webhook" | jq -r '.data.task_id')

echo "Task ID: $TASK_ID"

# Step 2: Poll sampai selesai (ulangi; patuhi saran "poll_after" pada response)
curl -X GET "https://docling.gai.co.id/api/v1/tasks/${TASK_ID}" \
  -H "Authorization: Bearer YOUR_TOKEN"
# Ulangi sampai status = "completed" (atau terminal lain)

# Step 3: Ambil hasil (hasil TIDAK dikirim inline di response poll)
curl -X GET "https://docling.gai.co.id/api/v1/tasks/${TASK_ID}/result" \
  -H "Authorization: Bearer YOUR_TOKEN" -o hasil.json
```

### 13. Konversi Asynchronous dengan Page Range

```bash
# Submit task dengan page range (hanya halaman 5-20)
TASK_ID=$(curl -s -X POST "https://docling.gai.co.id/api/v1/convert_async" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/large_document.pdf" \
  -F "enable_ocr=true" \
  -F "output_type=markdown" \
  -F "from_page=5" \
  -F "to_page=20" | jq -r '.data.task_id')

# Poll sampai selesai
curl -X GET "https://docling.gai.co.id/api/v1/tasks/${TASK_ID}" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 14. Konversi + Chunking Asynchronous

```bash
# Submit task
TASK_ID=$(curl -s -X POST "https://docling.gai.co.id/api/v1/convert_n_chunk_async" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@/path/to/large_document.pdf" \
  -F "enable_ocr=true" \
  -F "max_tokens=1024" \
  -F "chunk_type=hybrid" | jq -r '.data.task_id')

# Poll hasil
curl -X GET "https://docling.gai.co.id/api/v1/tasks/${TASK_ID}" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 15. List Semua Task Async

```bash
curl -X GET "https://docling.gai.co.id/api/v1/tasks?limit=10&offset=0" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Contoh Penggunaan (Python)

```python
import requests

BASE_URL = "https://docling.gai.co.id"
TOKEN = "your_bearer_token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# --- Konversi sederhana ---
with open("dokumen.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/api/v1/convert",
        headers=HEADERS,
        files={"file": ("dokumen.pdf", f, "application/pdf")},
        data={
            "enable_ocr": "false",
            "output_type": "markdown"
        }
    )

result = response.json()
if result["status"] == 0:
    print(result["data"]["content"])     # Markdown output
    print(f"Waktu: {result['data']['processing_time']}s")
else:
    print(f"Error: {result['error_message']}")


# --- Konversi dengan ekstraksi gambar (PDF) ---
with open("dokumen_dengan_gambar.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/api/v1/convert",
        headers=HEADERS,
        files={"file": ("dokumen_dengan_gambar.pdf", f, "application/pdf")},
        data={
            "enable_ocr": "false",
            "output_type": "markdown",
            "generate_picture_images": "true"
        }
    )

result = response.json()
if result["status"] == 0:
    print(result["data"]["content"])  # Markdown with embedded images


# --- Konversi halaman tertentu (page range) ---
with open("dokumen.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/api/v1/convert",
        headers=HEADERS,
        files={"file": ("dokumen.pdf", f, "application/pdf")},
        data={
            "output_type": "markdown",
            "from_page": "3",    # halaman awal (1-based, inklusif)
            "to_page": "7"       # halaman akhir (1-based, inklusif)
        }
    )

result = response.json()
if result["status"] == 0:
    print(result["data"]["content"])  # Hanya halaman 3-7


# --- Konversi + Chunking ---
with open("dokumen.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/api/v1/convert_n_chunk",
        headers=HEADERS,
        files={"file": ("dokumen.pdf", f, "application/pdf")},
        data={
            "enable_ocr": "false",
            "max_tokens": "1024",
            "output_type": "markdown",
            "chunk_type": "hybrid"
        }
    )

result = response.json()
if result["status"] == 0:
    print(f"Total chunks: {result['data']['total_chunks']}")
    for chunk in result["data"]["chunks"]:
        print(f"--- Chunk {chunk['chunk_id']} ({chunk['token_count']} tokens) ---")
        print(chunk["content"][:200])


# --- Konversi teks/markdown langsung dari database (tanpa file) ---
markdown_from_db = "# Judul\n\nKonten markdown dari database..."
response = requests.post(
    f"{BASE_URL}/api/v1/convert_text",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={
        "content": markdown_from_db,
        "filename": "document.md",
        "output_type": "markdown"
    }
)

result = response.json()
if result["status"] == 0:
    print(result["data"]["content"])


# --- Chunk teks/markdown dari database (tanpa file, untuk RAG) ---
markdown_from_db = "# Judul\n\nParagraf 1...\n\n## Sub\n\nParagraf 2..."
response = requests.post(
    f"{BASE_URL}/api/v1/chunk_text",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={
        "content": markdown_from_db,
        "filename": "document.md",
        "max_tokens": 512,
        "chunk_type": "hybrid"
    }
)

result = response.json()
if result["status"] == 0:
    print(f"Total chunks: {result['data']['total_chunks']}")
    for chunk in result["data"]["chunks"]:
        print(f"--- Chunk {chunk['chunk_id']} ({chunk['token_count']} tokens) ---")
        print(chunk["content"][:200])
```

---

## Resumable Upload dengan Python (File Besar)

```python
import requests
import os

BASE_URL = "https://docling.gai.co.id"
TOKEN = "your_bearer_token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
FILE_PATH = "big_document.pdf"
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB per chunk

file_size = os.path.getsize(FILE_PATH)
filename = os.path.basename(FILE_PATH)

# Step 1: Init upload
resp = requests.post(
    f"{BASE_URL}/api/v1/upload/init",
    headers=HEADERS,
    data={"filename": filename, "total_size": str(file_size)}
)
upload_id = resp.json()["data"]["upload_id"]
print(f"Upload ID: {upload_id}")

# Step 2: Upload in chunks
with open(FILE_PATH, "rb") as f:
    offset = 0
    while True:
        chunk = f.read(CHUNK_SIZE)
        if not chunk:
            break
        end = offset + len(chunk) - 1
        resp = requests.put(
            f"{BASE_URL}/api/v1/upload/{upload_id}",
            headers={
                **HEADERS,
                "Content-Type": "application/octet-stream",
                "Content-Range": f"bytes {offset}-{end}/{file_size}"
            },
            data=chunk
        )
        progress = resp.json()["data"]["progress"]
        print(f"Progress: {progress}%")
        offset += len(chunk)

# Step 3: Convert using upload_id
resp = requests.post(
    f"{BASE_URL}/api/v1/convert",
    headers=HEADERS,
    data={
        "upload_id": upload_id,
        "enable_ocr": "false",
        "output_type": "markdown"
    }
)
result = resp.json()
print(result["data"]["content"][:500])
```

---

## Async Task dengan Python (File Besar/Proses Lama)

```python
import requests
import time

BASE_URL = "https://docling.gai.co.id"
TOKEN = "your_bearer_token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# --- Submit async conversion task ---
with open("large_document.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/api/v1/convert_async",
        headers=HEADERS,
        files={"file": ("large_document.pdf", f, "application/pdf")},
        data={
            "enable_ocr": "true",
            "output_type": "markdown",
            # Opsional: notifikasi webhook saat status terminal + override timeout
            "callback_url": "https://your-app.example.com/webhook",
            # "timeout_seconds": "5400",
        }
    )

task_data = response.json()["data"]
task_id = task_data["task_id"]
poll_url = task_data["poll_url"]
print(f"Task submitted: {task_id}")
print(f"Poll URL: {poll_url}")

# --- Poll until completed ---
POLL_INTERVAL = 10  # seconds between polls
MAX_WAIT = 7200     # max 2 hours

elapsed = 0
while elapsed < MAX_WAIT:
    time.sleep(POLL_INTERVAL)
    elapsed += POLL_INTERVAL

    resp = requests.get(f"{BASE_URL}{poll_url}", headers=HEADERS)
    result = resp.json()["data"]
    status = result["status"]

    print(f"[{elapsed}s] Status: {status}")

    if status == "completed":
        # Hasil tidak inline: ambil via result_url (presigned) atau endpoint /result
        result_url = result.get("result_url", f"/api/v1/tasks/{task_id}/result")
        if result_url.startswith("http"):
            content_resp = requests.get(result_url)
        else:
            content_resp = requests.get(f"{BASE_URL}{result_url}", headers=HEADERS)
        payload = content_resp.json()
        content = payload.get("content") or payload.get("conversion", {}).get("content", "")
        print(f"\nDone in {result['processing_time']}s")
        print(f"Content length: {len(content)} chars")
        print(content[:500])
        break

    elif status == "failed":
        print(f"Task failed: {result['error']}")
        break

    elif status in ("expired", "timeout", "cancelled"):
        print(f"Task ended with status '{status}': {result.get('error')}")
        break
else:
    print("Polling timed out. Task may still be running.")


# --- Async convert + chunk ---
with open("large_document.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/api/v1/convert_n_chunk_async",
        headers=HEADERS,
        files={"file": ("large_document.pdf", f, "application/pdf")},
        data={
            "enable_ocr": "true",
            "max_tokens": "1024",
            "chunk_type": "hybrid"
        }
    )

task_id = response.json()["data"]["task_id"]
print(f"Chunk task submitted: {task_id}")

# Poll similarly as above...
poll_url = f"/api/v1/tasks/{task_id}"
# (same polling loop as above, result will contain chunks)


# --- List all tasks ---
resp = requests.get(
    f"{BASE_URL}/api/v1/tasks",
    headers=HEADERS,
    params={"limit": 10, "offset": 0}
)

tasks = resp.json()["data"]["tasks"]
for t in tasks:
    print(f"{t['task_id'][:8]}... | {t['status']:12s} | {t['endpoint']}")
```
