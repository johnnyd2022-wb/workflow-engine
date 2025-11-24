import fitz  # PyMuPDF
import sys

def extract_text_from_pdf(file_path):
    try:
        # Open the PDF file
        doc = fitz.open(file_path)
        print(f"Opened {file_path} with {len(doc)} pages.")
        
        # Loop through pages and extract text
        for page_number in range(len(doc)):
            page = doc[page_number]
            print(f"\n--- Page {page_number + 1} ---")
            print(page.get_text("text"))  # Extract text in plain format

    except Exception as e:
        print(f"Error: {e}")

# Check if file path is provided
if len(sys.argv) < 2:
    print("Usage: python extract_pdf.py <path-to-pdf>")
else:
    extract_text_from_pdf(sys.argv[1])
