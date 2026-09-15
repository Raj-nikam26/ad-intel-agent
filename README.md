# ExcelAI (Ad Intelligence Workspace)

ExcelAI is a premium, AI-powered spreadsheet intelligence tool. It combines the familiar, productive interface of Excel with the power of conversational AI. Upload your datasets, ask questions in plain English, visualize entity relationships, and let the AI automatically detect and fix data quality issues.

## ✨ Features

* **Conversational AI Assistant**: Ask questions about your data, request specific data cleaning operations, and get instant answers powered by LLMs (via OpenRouter).
* **Familiar Spreadsheet UI**: A high-performance virtualized grid featuring column letters, row numbers, cell focus, and sorting—just like MS Excel.
* **Smart Diagnostics**: Automatically detect missing values, mismatched names, and data anomalies.
* **Knowledge Graph**: Visualize relationships between entities (e.g., Advertisers, Categories, Offices) using an interactive network graph.
* **Audit Trail & Versioning**: Every AI-driven change is tracked. Roll back to any previous version of your dataset and compare diffs easily.
* **Privacy First**: Data is kept locally on your machine. Only the necessary schema and contextual data are sent to the LLM for reasoning.

## 🛠 Tech Stack

* **Frontend**: React, Vite, Lucide-React (Icons), Custom CSS (MNC-grade light theme)
* **Backend**: Python, FastAPI, Pandas (Data processing), NetworkX (Graph building), OpenAI Python SDK (Routing to OpenRouter)

## 🚀 Getting Started

### Prerequisites
* Python 3.9+
* Node.js 18+

### 1. Backend Setup
Navigate to the backend directory and set up the Python environment:

```bash
cd backend
python -m venv venv

# Activate the virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY

# Start the FastAPI server
uvicorn app.main:app --reload
```

### 2. Frontend Setup
Navigate to the frontend directory and start the Vite dev server:

```bash
cd frontend
npm install
npm run dev
```

The application will be available at `http://localhost:5173` (or the port specified by Vite).

## 💡 Usage

1. Open the web interface.
2. Drag and drop your `.xlsx` or `.xls` file into the upload zone.
3. Open the **AI Assistant** panel from the top right ribbon.
4. Try asking things like:
   * *"What data quality issues exist in this file?"*
   * *"How many rows are missing a Category value?"*
   * *"Fix the missing values in the Category column."*
5. Once you are happy with the cleaned data, click **Export** in the top ribbon to download the updated spreadsheet.