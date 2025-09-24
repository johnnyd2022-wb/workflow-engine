from decimal import Decimal, ROUND_HALF_UP
import os
import re
import fitz  # PyMuPDF
import sys
import json
from datetime import datetime, date
from initialize import db_conn
from database_insert import insert_data, update_data

def extract_products_from_invoice(section):
    """
    Extract all products from an invoice section.
    Returns a list of dictionaries with product details.
    """
    products = []
    
    # Debug: Check if this is INV-0012 or INV-0011
    is_inv_0012 = "INV-0012" in section
    is_inv_0011 = "INV-0011" in section
    
    # Find the products section - starts after "Amount NZD" header and before "Subtotal"
    # Updated pattern to handle both formats: "Amount NZD" on its own line OR as part of column headers
    products_pattern = r"(?:Amount\s+NZD\s*\n|Amount\s+NZD\s+)(.*?)(?=Subtotal|TOTAL)"
    products_match = re.search(products_pattern, section, re.DOTALL)
    
    # For INV-0011, just track what happened without verbose logging
    if is_inv_0011:
        global inv_0011_debug_info
        inv_0011_debug_info = {
            "regex_match": products_match is not None,
            "section_contains_amount_nzd": "Amount NZD" in section,
            "section_contains_subtotal": "Subtotal" in section,
            "section_contains_total": "TOTAL" in section
        }
        
        # Add captured text and lines info
        if products_match:
            captured_text = products_match.group(1).strip()
            lines = [line.strip() for line in captured_text.split('\n') if line.strip()]
            inv_0011_debug_info.update({
                "captured_text": captured_text,
                "lines_found": len(lines),
                "lines": lines
            })
    
    if not products_match:
        if is_inv_0012:
            print(f"DEBUG: INV-0012 - No products section found. Section preview: {section[:200]}...")
            print(f"DEBUG: INV-0012 - Looking for pattern: 'Amount\\s+NZD\\s*\\n(.*?)(?=Subtotal|TOTAL)'")
            print(f"DEBUG: INV-0012 - Section contains 'Amount NZD': {'Amount NZD' in section}")
            print(f"DEBUG: INV-0012 - Section contains 'Subtotal': {'Subtotal' in section}")
            print(f"DEBUG: INV-0012 - Section contains 'TOTAL': {'TOTAL' in section}")
        elif is_inv_0011:
            print(f"DEBUG: INV-0011 - No products section found. Section preview: {section[:300]}...")
            print(f"DEBUG: INV-0011 - Looking for pattern: 'Amount\\s+NZD\\s*\\n(.*?)(?=Subtotal|TOTAL)'")
            print(f"DEBUG: INV-0011 - Section contains 'Amount NZD': {'Amount NZD' in section}")
            print(f"DEBUG: INV-0011 - Section contains 'Subtotal': {'Subtotal' in section}")
            print(f"DEBUG: INV-0011 - Section contains 'TOTAL': {'TOTAL' in section}")
            print(f"DEBUG: INV-0011 - Full section text: {section}")
        else:
            print("No products section found in invoice")
            # Add general debugging for all invoices
            print(f"DEBUG: Section preview: {section[:300]}...")
            print(f"DEBUG: Section contains 'Amount NZD': {'Amount NZD' in section}")
            print(f"DEBUG: Section contains 'Subtotal': {'Subtotal' in section}")
            print(f"DEBUG: Section contains 'TOTAL': {'TOTAL' in section}")
        return products
    
    products_text = products_match.group(1).strip()
    
    if is_inv_0012:
        print(f"DEBUG: INV-0012 - Products section found! Text: {products_text[:200]}...")
    elif is_inv_0011:
        print(f"DEBUG: INV-0011 - Products section found! Text: {products_text[:300]}...")
    
    # Split into lines and process
    lines = [line.strip() for line in products_text.split('\n') if line.strip()]
    
    if is_inv_0012:
        print(f"DEBUG: INV-0012 - Total lines found: {len(lines)}")
        print(f"DEBUG: INV-0012 - Lines: {lines}")
    elif is_inv_0011:
        print(f"DEBUG: INV-0011 - Total lines found: {len(lines)}")
        print(f"DEBUG: INV-0011 - Lines: {lines}")
    
    # Process lines more intelligently - look for product patterns
    i = 0
    
    # Debug: Track product parsing for INV-0011
    if is_inv_0011:
        print(f"DEBUG: INV-0011 - Starting product parsing with {len(lines)} lines")
        print(f"DEBUG: INV-0011 - Lines to process: {lines}")
    
    while i < len(lines):
        try:
            # Product name (may span multiple lines, but we'll take the first meaningful one)
            product_name = lines[i]
            
            # Debug: Track each step for INV-0011
            if is_inv_0011:
                print(f"DEBUG: INV-0011 - Processing line {i}: '{product_name}'")
            
            # Extract the base product name (remove " - x1" suffix if present)
            clean_name = re.sub(r'\s+-\s+x\d+$', '', product_name)
            
            # Skip shipping line items (they are free)
            if 'shipping' in clean_name.lower():
                if is_inv_0011:
                    print(f"DEBUG: INV-0011 - Skipping shipping line item: {clean_name}")
                # Skip to the next line and continue
                i += 1
                continue
            
            # Extract only the core product name (wildflower or solstice) in lowercase
            if 'wildflower' in clean_name.lower():
                clean_name = 'wildflower'
            elif 'solstice' in clean_name.lower():
                clean_name = 'solstice'
            elif 'rosella' in clean_name.lower():
                clean_name = 'rosella'
            else:
                # Keep original if neither wildflower nor solstice found
                clean_name = clean_name.lower().strip()
            
            # Look ahead to see if we have a complete product (name, qty, price, amount)
            if i + 3 >= len(lines):
                break  # Not enough lines left
                
            # Check if the next 3 lines are numeric (quantity, price, amount)
            if is_inv_0011:
                print(f"DEBUG: INV-0011 - Checking lines {i+1}, {i+2}, {i+3} for product data")
                print(f"DEBUG: INV-0011 - Line {i+1}: '{lines[i+1]}'")
                print(f"DEBUG: INV-0011 - Line {i+2}: '{lines[i+2]}'")
                print(f"DEBUG: INV-0011 - Line {i+3}: '{lines[i+3]}'")
            
            try:
                # Clean numeric strings by removing commas before converting to float
                quantity = float(lines[i + 1].replace(',', ''))
                unit_price = float(lines[i + 2].replace(',', ''))
                amount = float(lines[i + 3].replace(',', ''))
                
                if is_inv_0011:
                    print(f"DEBUG: INV-0011 - Successfully parsed: qty={quantity}, price={unit_price}, amount={amount}")
                    
            except (ValueError, IndexError) as e:
                # Not a complete product, move to next line
                if is_inv_0011:
                    print(f"DEBUG: INV-0011 - Line {i} doesn't have complete product data: {e}")
                    print(f"DEBUG: INV-0011 - Moving to next line")
                i += 1
                continue
            
            # We have a complete product!
            product = {
                "name": clean_name,
                "quantity": int(quantity),
                "unit_price": unit_price,
                "amount": amount
            }
            
            products.append(product)
            if is_inv_0011:
                print(f"DEBUG: INV-0011 - Successfully extracted product: {clean_name} - Qty: {quantity}, Price: ${unit_price:.2f}, Amount: ${amount:.2f}")            
            # Move to next potential product
            i += 4
            
        except (ValueError, IndexError) as e:
            print(f"Error parsing product at line {i}: {e}")
            i += 1
    
    return products

def create_products_json(products, invoice_details):
    """
    Create the JSONB structure for products with all line item information.
    Structure: {"products": {"product_name": {"quantity": X, "unit_price": Y, ...}}}
    """
    products_data = {}
    
    for product in products:
        product_name = product["name"]
        
        # Calculate product-specific values
        number_of_bottles = product["quantity"]
        unit_price = product["unit_price"]
        amount_nzd = product["amount"]
        
        # Calculate ABV based on product name
        abv = 44.0 if 'wildflower' in product_name.lower() else 40.0 if 'solstice' in product_name.lower() else 40.0 if 'rosella' in product_name.lower() else 40.0
        
        # Calculate LAL and duty
        bottle_size_ml = 700.0
        duty_price = 67.22
        total_alcohol_ml = number_of_bottles * bottle_size_ml * abv
        lal = total_alcohol_ml / 100000
        duty_amount = lal * duty_price
        rounded_duty_amount = Decimal(duty_amount).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
        
        # Get bottle batch
        bottle_batch = get_bottle_batch(invoice_details['Invoice Date'])
        
        # Calculate GST proportion for this line item
        num_line_items = len(products)
        if num_line_items == 1:
            line_item_total = invoice_details['Total NZD']
            line_item_gst = invoice_details['GST']
        else:
            line_item_total = amount_nzd
            line_item_gst = (amount_nzd / invoice_details['Total NZD']) * invoice_details['GST']
        
        # Store product data under the product name key
        products_data[product_name] = {
            "quantity": number_of_bottles,
            "unit_price": unit_price,
            "amount_nzd": amount_nzd,
            "total_nzd": line_item_total,
            "gst": line_item_gst,
            "abv": abv,
            "bottle_size_ml": bottle_size_ml,
            "lal": lal,
            "duty_amount": float(rounded_duty_amount),
            "bottle_batch": bottle_batch
        }
    
    return {"products": products_data}

def get_bottle_batch(invoice_date):
    """
    Get the appropriate bottle batch for the given invoice date.
    """
    connection, cursor = db_conn()
    
    try:
        query = """
        SELECT bottle_batch, MIN(date) as earliest_date
        FROM product_actions_bottling
        GROUP BY bottle_batch
        ORDER BY earliest_date;
        """
        cursor.execute(query)
        batch_dates = cursor.fetchall()
        
        new_invoice_date = datetime.strptime(invoice_date, '%Y-%m-%d').date()
        selected_batch = None
        
        # Iterate through the batches
        for i, record in enumerate(batch_dates):
            bottle_batch, earliest_date = record
            
            # Ensure that earliest_date is already a datetime.date object
            if isinstance(earliest_date, datetime):
                earliest_date = earliest_date.date()
            
            if new_invoice_date >= earliest_date:
                if i + 1 < len(batch_dates):
                    next_batch, next_earliest_date = batch_dates[i + 1]
                    
                    # Ensure that next_earliest_date is also a datetime.date object
                    if isinstance(next_earliest_date, datetime):
                        next_earliest_date = next_earliest_date.date()
                    
                    if new_invoice_date < next_earliest_date:
                        selected_batch = bottle_batch
                        break
                else:
                    # If it's the last batch, select it
                    selected_batch = bottle_batch
                    break
        
        if selected_batch is None:
            print("No valid bottle_batch found for the given invoice_date.")
            return None
            
        return f"{{{selected_batch}}}"
        
    finally:
        cursor.close()
        connection.close()

def extract_sales_pdf_data(directory):
    """
    Processes all PDF files in a directory, extracts specific fields,
    formats the results, and ensures no duplicate invoices are processed
    based on the combination of Company Name, Invoice Date, and Invoice Number.
    Handles files with multiple invoices by splitting text on "PAYMENT ADVICE".
    Now supports multiple products per invoice using JSONB structure.
    """
    extracted_data = {}
    processed_combinations = set()  # Set to track processed combinations of (Company Name, Invoice Date, Invoice Number)
    
    # Store raw text for INV-0011 debugging
    inv_0011_raw_text = None
    
    # Global variable to store INV-0011 debug info
    global inv_0011_debug_info
    inv_0011_debug_info = None
    


    # Adjusted regex patterns based on provided raw text
    basic_patterns = {
        "Company Name": r"TAX INVOICE\s+([^\n]+)\n",  # Matches text after "TAX INVOICE"
        "Invoice Date": r"Invoice Date\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",  # Matches date like "11 Jan 2025"
        "Invoice Number": r"Invoice Number\s+(\S+)",  # Matches the invoice number after "Invoice Number"
        "Total NZD":  r"TOTAL\s+NZD.*?\n\s*([\d,]+\.\d+)", # Matches the value for Total NZD
        "GST": r"TOTAL\s\s+GST\s\s+15%.*?\n\s*([\d,]+\.\d+)", # Matches the value for GST
    }

    # Collect all invoices first, then sort them
    all_invoices = []
    
    # Iterate through files in the directory
    for filename in os.listdir(directory):
        if filename.endswith(".pdf"):
            file_path = os.path.join(directory, filename)
            


            try:
                # Read the PDF content using fitz (PyMuPDF)
                doc = fitz.open(file_path)
                text = ""
                for page in doc:
                    text += page.get_text()



                # Split the text into sections using "PAYMENT ADVICE"
                invoice_sections = text.split("PAYMENT ADVICE")[1:]  # Ignore the first empty split

                # Print the raw text for debugging
                #print(f"printing raw invoices")
                #print(f"--- Raw Text from {filename} ---")
                #print(text)
                #print("--- End of Text ---\n")
                
                # Store raw text for INV-0011 debugging
                if "INV-0011" in text:
                    inv_0011_raw_text = text
                    print(f"DEBUG: Captured raw text for INV-0011 from {filename}")

                for section in invoice_sections:
                    # Extract basic invoice fields
                    file_data = {}
                    for field, pattern in basic_patterns.items():
                        match = re.search(pattern, section, re.DOTALL)
                        file_data[field] = match.group(1).strip() if match else None

                    # Extract multiple products from the invoice
                    products = extract_products_from_invoice(section)
                    file_data["products"] = products

                    # Calculate totals
                    total_quantity = sum(product["quantity"] for product in products)
                    file_data["total_quantity"] = total_quantity

                    # Format the extracted data
                    if file_data["Company Name"]:
                        file_data["Company Name"] = " ".join(file_data["Company Name"].replace("\n", " ").split())

                    if file_data["Invoice Date"]:
                        try:
                            date_obj = datetime.strptime(file_data["Invoice Date"], "%d %b %Y")
                            file_data["Invoice Date"] = date_obj.strftime("%Y-%m-%d")
                        except ValueError:
                            print(f"Error parsing date for {filename}: {file_data['Invoice Date']}")

                    # Format numeric fields to float and remove commas
                    if file_data.get("Total NZD"):
                        file_data["Total NZD"] = float(file_data["Total NZD"].replace(",", ""))

                    if file_data.get("GST"):
                        file_data["GST"] = float(file_data["GST"].replace(",", ""))

                    # Check for duplicates
                    combination = (file_data["Invoice Date"], file_data["Invoice Number"])
                    if combination in processed_combinations:
                        print(f"Skipping duplicate invoice: {file_data['Invoice Number']} from {file_data['Company Name']}")
                        continue
                    
                    # Debug logging for specific invoice
                    if file_data["Invoice Number"] == "INV-0012":
                        print(f"DEBUG: INV-0012 found - Company: {file_data['Company Name']}, Date: {file_data['Invoice Date']}, Products: {len(products)}")
                        print(f"DEBUG: INV-0012 combination: {combination}")
                        print(f"DEBUG: INV-0012 processed_combinations contains: {combination in processed_combinations}")

                    # Print product summary
                    print(f"Invoice {file_data['Invoice Number']} contains {len(products)} products:")
                    for product in products:
                        print(f"  - {product['name']}: {product['quantity']} bottles @ ${product['unit_price']:.2f} each = ${product['amount']:.2f}")
                    print(f"  Total bottles: {total_quantity}")
                    print(f"  Total amount: ${file_data['Total NZD']:.2f}")

                    # Store the invoice data for sorting
                    all_invoices.append({
                        'filename': filename,
                        'file_data': file_data,
                        'combination': combination
                    })
                    processed_combinations.add(combination)
                    
                    # Debug logging for specific invoice
                    if file_data["Invoice Number"] == "INV-0012":
                        print(f"DEBUG: INV-0012 added to all_invoices list. Current count: {len(all_invoices)}")

            except Exception as e:
                print(f"Error processing {filename}: {e}")

    # Sort invoices by invoice number in descending order (highest first)
    def extract_invoice_number(invoice_info):
        """Extract numeric part from invoice number for sorting"""
        invoice_num = invoice_info['file_data']['Invoice Number']
        if invoice_num and invoice_num.startswith('INV-'):
            try:
                # Extract the numeric part after 'INV-' and convert to int
                numeric_part = int(invoice_num[4:])
                return numeric_part
            except ValueError:
                # If conversion fails, return 0 to put it at the end
                return 0
        return 0

    # Sort in descending order (highest invoice numbers first)
    all_invoices.sort(key=extract_invoice_number, reverse=True)
    
    print(f"\n=== INVOICES SORTED BY NUMBER (DESCENDING) ===")
    for i, invoice_info in enumerate(all_invoices):
        invoice_num = invoice_info['file_data']['Invoice Number']
        numeric_part = extract_invoice_number(invoice_info)
        print(f"{i+1}. {invoice_num} (numeric: {numeric_part})")
    print("=== END SORTED LIST ===\n")

    # Now organize the sorted invoices into the extracted_data structure
    for invoice_info in all_invoices:
        filename = invoice_info['filename']
        file_data = invoice_info['file_data']
        extracted_data.setdefault(filename, []).append(file_data)
        
        # Debug logging for specific invoice
        if file_data["Invoice Number"] == "INV-0012":
            print(f"DEBUG: INV-0012 added to extracted_data for file: {filename}")
            print(f"DEBUG: INV-0012 products: {len(file_data.get('products', []))}")

    # Insert into the database
    if extracted_data:
        connection, cursor = db_conn()

        for file, invoices in extracted_data.items():
            for invoice_details in invoices:
                try:
                    # Debug logging for specific invoice
                    if invoice_details["Invoice Number"] == "INV-0012":
                        print(f"DEBUG: INV-0012 reached database processing loop")
                        print(f"DEBUG: INV-0012 file: {file}, products: {len(invoice_details['products'])}")
                    
                    # Create the JSONB structure for all products in this invoice
                    products_json = create_products_json(invoice_details["products"], invoice_details)
                    
                    # Check for existing entries in the database using notes
                    notes = f"{{{invoice_details['Invoice Number']}}}"
                    wildcard_notes = f"%{notes}%"
                    
                    # Check if there's an entry with this specific invoice
                    check_invoice_query = "SELECT COUNT(*) FROM sales_product WHERE notes LIKE %s;"
                    cursor.execute(check_invoice_query, (wildcard_notes,))
                    invoice_exists = cursor.fetchone()[0]

                    if invoice_exists > 0:
                        print(f"Entry exists for {notes}. Checking for missing column values...")
                        
                        # Check each column individually and update if missing
                        check_columns_query = """
                        SELECT buyer, products, invoice_total, invoice_gst
                        FROM sales_product WHERE notes LIKE %s;
                        """
                        cursor.execute(check_columns_query, (wildcard_notes,))
                        existing_data = cursor.fetchone()
                        
                        if existing_data:
                            existing_buyer, existing_products, existing_invoice_total, existing_invoice_gst = existing_data
                            
                            # Check and update each missing field
                            updates = {}
                            
                            if existing_buyer is None:
                                updates['buyer'] = invoice_details['Company Name']
                            if existing_products is None:
                                updates['products'] = json.dumps(products_json)
                            if existing_invoice_total is None:
                                updates['invoice_total'] = invoice_details['Total NZD']
                            if existing_invoice_gst is None:
                                updates['invoice_gst'] = invoice_details['GST']
                            
                            if updates:
                                print(f"Updating missing fields for {notes}: {list(updates.keys())}")
                                update_data(table_name='sales_product', condition={'notes': notes}, **updates)
                            else:
                                print(f"All fields already populated for {notes}")
                        
                        continue

                    print(f"Inserting invoice {invoice_details['Invoice Number']} for {invoice_details['Company Name']} with {len(invoice_details['products'])} products on {invoice_details['Invoice Date']}")

                    # Insert the invoice with the JSONB products structure
                    insert_data(
                        table_name='sales_product',
                        audit_action='Bottle sales',
                        buyer=invoice_details['Company Name'],
                        products=json.dumps(products_json),
                        notes=notes,
                        invoice_total=invoice_details['Total NZD'],
                        invoice_gst=invoice_details['GST']
                    )
                    
                    # Update the date to the invoice date
                    update_data(table_name='sales_product', condition={'notes': notes}, date=invoice_details['Invoice Date'])

                except Exception as e:
                    print(f"Error inserting data for {file}: {e}")

        cursor.close()
        connection.close()


    
    # Debug output for INV-0011
    print("\n" + "="*50)
    print("DEBUG: INV-0011 ANALYSIS")
    print("="*50)
    
    # Find INV-0011 in the extracted data
    inv_0011_found = False
    for filename, invoices in extracted_data.items():
        for invoice in invoices:
            if invoice.get("Invoice Number") == "INV-0011":
                inv_0011_found = True
                print(f"INV-0011 found in file: {filename}")
                print(f"Company: {invoice.get('Company Name')}")
                print(f"Date: {invoice.get('Invoice Date')}")
                print(f"Total NZD: {invoice.get('Total NZD')}")
                print(f"GST: {invoice.get('GST')}")
                print(f"Products extracted: {len(invoice.get('products', []))}")
                
                if invoice.get('products'):
                    print("Product details:")
                    for i, product in enumerate(invoice['products']):
                        print(f"  Product {i+1}: {product}")
                else:
                    print("  No products found!")
                    print("  This suggests the extract_products_from_invoice() function failed")
                    print("  Check the regex pattern and text structure for this invoice")
                
                print(f"Total quantity: {invoice.get('total_quantity')}")
                
                # Additional debugging: Show the raw text section that was processed
                print("\n  Raw text analysis:")
                for filename, invoices in extracted_data.items():
                    for invoice_check in invoices:
                        if invoice_check.get("Invoice Number") == "INV-0011":
                            # Find the original section text that was processed
                            print(f"  Invoice section preview: {str(invoice_check)[:300]}...")
                            break
                
                # Print the actual raw text content that was processed for INV-0011
                print("\n  ACTUAL RAW TEXT CONTENT FOR INV-0011:")
                print("  " + "="*60)
                if inv_0011_raw_text:
                    print("  Raw text from PDF:")
                    print("  " + inv_0011_raw_text)
                    print("  " + "="*60)
                else:
                    print("  No raw text captured for INV-0011")
                
                # Add the debug info from the product extraction function
                print("\n  PRODUCT EXTRACTION DEBUG INFO:")
                print("  " + "="*60)
                if inv_0011_debug_info:
                    print(f"  Regex match found: {inv_0011_debug_info['regex_match']}")
                    print(f"  Section contains 'Amount NZD': {inv_0011_debug_info['section_contains_amount_nzd']}")
                    print(f"  Section contains 'Subtotal': {inv_0011_debug_info['section_contains_subtotal']}")
                    print(f"  Section contains 'TOTAL': {inv_0011_debug_info['section_contains_total']}")
                    
                    # Add more detailed debug info
                    if inv_0011_debug_info.get('captured_text'):
                        print(f"  Captured text preview: {inv_0011_debug_info['captured_text'][:200]}...")
                    if inv_0011_debug_info.get('lines_found'):
                        print(f"  Lines found: {inv_0011_debug_info['lines_found']}")
                    if inv_0011_debug_info.get('lines'):
                        print(f"  Individual lines: {inv_0011_debug_info['lines']}")
                else:
                    print("  No debug info available - function may not have been called")
                print("  " + "="*60)
                break
        if inv_0011_found:
            break
    
    if not inv_0011_found:
        print("INV-0011 NOT FOUND in extracted data!")
    
    print("="*50)
    print("END INV-0011 DEBUG")
    print("="*50 + "\n")
    
    # Return extracted data
    return extracted_data

# Call the function with the directory path
extracted_data = extract_sales_pdf_data("./invoices")
