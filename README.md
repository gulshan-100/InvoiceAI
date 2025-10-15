# AI Invoice Manager

A Django application that uses AI-powered OCR and GPT models to extract structured data from invoice images, store it in MongoDB, and allow easy viewing and download of processed invoice data.

## Features

- **AI-powered Invoice Processing**: Leverages OpenAI's GPT-4o model for OCR and text extraction
- **Parallel Processing**: Uses Celery for asynchronous processing of multiple invoices simultaneously
- **Structured Data Extraction**: Extracts vendor details, invoice details, line items, and totals
- **Data Validation**: AI-based validation to detect calculation errors and suspicious invoice data
- **MongoDB Storage**: Stores all extracted invoice data in MongoDB for easy querying
- **Modern Web Interface**: Clean, responsive UI for uploading and managing invoices
- **Export to CSV**: Download all invoice data in CSV format for analysis

## Technology Stack

- **Backend**: Django, Celery
- **AI Processing**: OpenAI GPT-4o, LangChain, LangGraph
- **Database**: MongoDB
- **Queue/Task Management**: Redis
- **Frontend**: HTML, CSS, JavaScript

## System Architecture

The application follows a modern architecture:

1. **Web Interface**: Allows uploading one or more invoice images
2. **Asynchronous Processing**: Delegates heavy processing to Celery workers
3. **AI Pipeline**:
   - OCR text extraction from invoice images
   - Structured data parsing from raw text
   - Invoice data validation
4. **Storage**: MongoDB for document storage
5. **API Endpoints**: RESTful endpoints for uploading, listing, and downloading invoice data

## Prerequisites

- Python 3.8+
- Redis server
- MongoDB server
- OpenAI API key

## Environment Variables

Create a `.env` file in the project root with:

```
OPENAI_API_KEY=your_openai_api_key
MONGO_URI=your_mongodb_connection_string
REDIS_URL=your_redis_url
MONGO_DB=invoice_ai  # optional, default: invoice_ai
MONGO_COLLECTION=invoices  # optional, default: invoices
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/gulshan100/aiinvoice.git
cd aiinvoice
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run migrations:
```bash
python manage.py migrate
```

## Running the Application

1. Start the Redis server (if not already running)

2. Start the Celery worker:
```bash
# On Windows
celery -A aiinvoice worker --pool=solo -l info
# On macOS/Linux
celery -A aiinvoice worker -l info
```

3. Run the Django development server:
```bash
python manage.py runserver
```

4. Open your browser and navigate to `http://127.0.0.1:8000/`

## API Endpoints

- `POST /api/upload_invoice/`: Upload one or more invoice images for processing
- `GET /api/list_invoices/`: List all processed invoices
- `GET /api/download_csv/`: Download all invoice data as CSV
- `GET /api/task_status/<task_id>/`: Check status of a specific processing task
- `GET /api/tasks_status/?task_id=<id1>&task_id=<id2>`: Check status of multiple processing tasks

## Project Structure

```
aiinvoice/           # Django project folder
  ├── settings.py    # Project settings
  ├── urls.py        # URL routing
  ├── celery.py      # Celery configuration
  └── ...
app/                 # Django app folder
  ├── views.py       # API endpoints and views
  ├── tasks.py       # Celery tasks
  ├── models.py      # Django models
  ├── utils/         # Utility modules
  │   ├── invoice_processor.py  # AI processing pipeline
  │   └── store_database.py     # MongoDB interface
  └── templates/     # Frontend templates
      └── upload.html           # Main interface
```

## Example Usage

1. Visit the main page at `http://127.0.0.1:8000/`
2. Upload one or more invoice images
3. Wait for processing to complete (progress is shown in real-time)
4. View the structured data extracted from invoices
5. Download all processed data as CSV for further analysis

## License

[Your License Here]

## Contributing

[Your Contribution Guidelines Here]