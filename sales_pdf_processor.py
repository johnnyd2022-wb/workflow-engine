from decimal import Decimal, ROUND_HALF_UP
import os
import re
import fitz  # PyMuPDF
from datetime import datetime, date
from initialize import db_conn
from database_insert import insert_data, update_data

def extract_sales_pdf_data(directory):
    """
    Processes all PDF files in a directory, extracts specific fields,
    formats the results, and ensures no duplicate invoices are processed
    based on the combination of Company Name, Invoice Date, and Invoice Number.
    Handles files with multiple invoices by splitting text on "PAYMENT ADVICE".
    """
    extracted_data = {}
    processed_combinations = set()  # Set to track processed combinations of (Company Name, Invoice Date, Invoice Number)

    # Adjusted regex patterns based on provided raw text
    patterns = {
        "Company Name": r"TAX INVOICE\s+([^\n]+)\n",  # Matches text after "TAX INVOICE"
        "Invoice Date": r"Invoice Date\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",  # Matches date like "11 Jan 2025"
        "Invoice Number": r"Invoice Number\s+(\S+)",  # Matches the invoice number after "Invoice Number"
        "Unit Price": r"Unit\s+Price\s+Amount\s+NZD.*?\n.*?\n.*?\s+([\d.]+)\s",  # Matches the value directly under "Unit Price"
        "Amount NZD": r"Amount\s+NZD.*?\n.*?\n.*?\n.*?\s+([\d,]+\.\d+)", # Matches the value for Amount NZD
        "Total NZD":  r"TOTAL\s+NZD.*?\n\s*([\d,]+\.\d+)", # Matches the value for Total NZD
        "GST": r"TOTAL\s\s+GST\s\s+15%.*?\n\s*([\d,]+\.\d+)", # Matches the value for GST
        "Quantity": r"Description\s+.*?\n([\d.]+)\s+"  # Matches quantity after "Description" line
    }

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

                print(f"Processing {filename}")

                # Split the text into sections using "PAYMENT ADVICE"
                invoice_sections = text.split("PAYMENT ADVICE")[1:]  # Ignore the first empty split

                # Print the raw text for debugging
                #print(f"--- Raw Text from {filename} ---")
                #print(text)
                #print("--- End of Text ---\n")

                for section in invoice_sections:
                    # Extract fields using regex
                    file_data = {}
                    for field, pattern in patterns.items():
                        match = re.search(pattern, section, re.DOTALL)
                        file_data[field] = match.group(1).strip() if match else None

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
                    if file_data.get("Amount NZD"):
                        file_data["Amount NZD"] = float(file_data["Amount NZD"].replace(",", ""))
                    if file_data.get("Total NZD"):
                        file_data["Total NZD"] = float(file_data["Total NZD"].replace(",", ""))

                    # Check for duplicates
                    combination = (file_data["Invoice Date"], file_data["Invoice Number"])
                    if combination in processed_combinations:
                        print(f"Skipping duplicate invoice: {file_data['Invoice Number']} from {file_data['Company Name']}")
                        continue

                    # Store the extracted data
                    extracted_data.setdefault(filename, []).append(file_data)
                    processed_combinations.add(combination)

            except Exception as e:
                print(f"Error processing {filename}: {e}")

    # Insert into the database
    if extracted_data:
        connection, cursor = db_conn()

        for file, invoices in extracted_data.items():
            for details in invoices:
                try:
                    # Same logic for inserting data as before
                    number_of_bottles = int(float(details['Quantity']))
                    buyer = details['Company Name']
                    notes = details['Invoice Number']
                    notes = f"{{{notes}}}"
                    invoice_date = details['Invoice Date']
                    unit_price = details['Unit Price']
                    amount_nzd = details['Amount NZD']
                    total_nzd = details['Total NZD']
                    gst = details['GST']
                    current_date = date.today()
                    bottle_size_ml = 700.0
                    abv = 44.0

                    # Check if unit_price is in the database
                    check_query = "SELECT unit_price FROM sales_product WHERE notes LIKE %s;"
                    wildcard_notes = f"%{notes}%"
                    cursor.execute(check_query, (wildcard_notes,))
                    result = cursor.fetchone()

                    if result is not None and result[0] is not None:
                        print(f"Entry already populated, proceeding to next invoice")
                    else:
                        # Update the missing fields if the record exists but values are missing
                        print(f"Updating missing data for invoice {notes} - Adding {unit_price}")
                        update_data(table_name='sales_product', condition={'notes': notes}, unit_price=unit_price)

                    # amount_nzd
                    check_query = "SELECT amount_nzd FROM sales_product WHERE notes LIKE %s;"
                    wildcard_notes = f"%{notes}%"
                    cursor.execute(check_query, (wildcard_notes,))
                    result = cursor.fetchone()

                    if result is not None and result[0] is not None:
                        print(f"Entry already populated, proceeding to next invoice")
                    else:
                        # Update the missing fields if the record exists but values are missing
                        print(f"Updating missing data for invoice {notes} - Adding {amount_nzd}")
                        update_data(table_name='sales_product', condition={'notes': notes}, amount_nzd=amount_nzd)

                    # total_nzd
                    check_query = "SELECT total_nzd FROM sales_product WHERE notes LIKE %s;"
                    wildcard_notes = f"%{notes}%"
                    cursor.execute(check_query, (wildcard_notes,))
                    result = cursor.fetchone()

                    if result is not None and result[0] is not None:
                        print(f"Entry already populated, proceeding to next invoice")
                    else:
                        # Update the missing fields if the record exists but values are missing
                        print(f"Updating missing data for invoice {notes} - Adding {total_nzd}")
                        update_data(table_name='sales_product', condition={'notes': notes}, total_nzd=total_nzd)

                    # gst check
                    check_query = "SELECT gst FROM sales_product WHERE notes LIKE %s;"
                    wildcard_notes = f"%{notes}%"
                    cursor.execute(check_query, (wildcard_notes,))
                    result = cursor.fetchone() 

                    if result is not None and result[0] is not None:
                        print(f"Entry already populated, proceeding to next invoice")
                    else:
                        # Update the missing fields if the record exists but values are missing
                        print(f"Updating missing data for invoice {notes} - Adding {gst}")
                        update_data(table_name='sales_product', condition={'notes': notes}, gst=gst)

                    # Check for existing entries in the database
                    check_query = "SELECT COUNT(*) FROM sales_product WHERE notes LIKE %s;"
                    wildcard_notes = f"%{notes}%"
                    cursor.execute(check_query, (wildcard_notes,))
                    count = cursor.fetchone()[0]

                    if count > 0:
                        print(f"Duplicate entry found: {notes}. Skipping insert.")
                        continue

                    print(f"Inserting invoice {details['Invoice Number']} for {details['Company Name']}. {details['Quantity']} bottles sold on {details['Invoice Date']}")

                    # Calculate Duty and insert logic
                    duty_price = 67.22
                    total_alcohol_ml = number_of_bottles * bottle_size_ml * abv
                    lal = total_alcohol_ml / 100000
                    duty_amount = lal * duty_price
                    rounded_duty_amount = Decimal(duty_amount).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)

                    # Fetch the correct bottle_batch
                    query = """
                    SELECT bottle_batch, MIN(date) as earliest_date
                    FROM product_actions_bottling
                    GROUP BY bottle_batch
                    ORDER BY earliest_date;
                    """
                    cursor.execute(query)

                    # Fetch all the results from the query
                    batch_dates = cursor.fetchall()

                    new_invoice_date = datetime.strptime(invoice_date, '%Y-%m-%d').date()
                    selected_batch = None

                    # Iterate through the batches
                    for i, record in enumerate(batch_dates):
                        bottle_batch, earliest_date = record

                        # Ensure that earliest_date is already a datetime.date object
                        if isinstance(earliest_date, datetime):
                            earliest_date = earliest_date.date()  # Convert to date if it's a datetime object

                        if new_invoice_date >= earliest_date:
                            if i + 1 < len(batch_dates):
                                next_batch, next_earliest_date = batch_dates[i + 1]
                                
                                # Ensure that next_earliest_date is also a datetime.date object
                                if isinstance(next_earliest_date, datetime):
                                    next_earliest_date = next_earliest_date.date()  # Convert to date if necessary
                                
                                if new_invoice_date < next_earliest_date:
                                    selected_batch = bottle_batch
                                    break
                            else:
                                # If it's the last batch, select it
                                selected_batch = bottle_batch
                                break

                    if selected_batch is None:
                        print("No valid bottle_batch found for the given invoice_date.")
                    selected_batch = f"{{{selected_batch}}}"

                    insert_data(
                        table_name='sales_product',
                        audit_action='Bottle sales',
                        buyer=buyer,
                        bottles_sold=number_of_bottles,
                        abv=abv,
                        bottle_size_ml=bottle_size_ml,
                        lal=lal,
                        duty_amount=rounded_duty_amount,
                        bottle_batch=selected_batch,
                        notes=notes
                    )
                    update_data(table_name='sales_product', condition={'date': current_date}, date=invoice_date)
                except Exception as e:
                    print(f"Error inserting data for {file}: {e}")

        cursor.close()
        connection.close()

    # Return extracted data
    return extracted_data

# Call the function with the directory path
extracted_data = extract_sales_pdf_data("./invoices")

#def update_buyers_table_from_pdf_data(directory):
#    """
#    Processes all PDF files in a directory, extracts specific fields,
#    formats the results, and ensures no duplicate invoices are processed
#    based on the combination of Company Name, Invoice Date, Amount and Invoice Number.
#    Handles files with multiple invoices by splitting text on "PAYMENT ADVICE".
#    """
#    extracted_data = {}
#    processed_combinations = set()  # Set to track processed combinations of (Company Name, Invoice Date, Invoice Number)
#
#    # Adjusted regex patterns based on provided raw text
#    patterns = {
#        "Company Name": r"TAX INVOICE\s+([^\n]+)\n",  # Matches text after "TAX INVOICE"
#        "Invoice Date": r"Invoice Date\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",  # Matches date like "11 Jan 2025"
#        "Invoice Number": r"Invoice Number\s+(\S+)",  # Matches the invoice number after "Invoice Number"
#        "Unit Price": r"Unit\s+Price\s+Amount\s+NZD.*?\n.*?\n.*?\s+([\d.]+)\s", # Matches the amount in the Unit Price
#        "Quantity": r"Description\s+.*?\n([\d.]+)\s+"  # Matches quantity after "Description" line
#    }
#
#    # Iterate through files in the directory
#    for filename in os.listdir(directory):
#        if filename.endswith(".pdf"):
#            file_path = os.path.join(directory, filename)
#
#            try:
#                # Read the PDF content using fitz (PyMuPDF)
#                doc = fitz.open(file_path)
#                text = ""
#                for page in doc:
#                    text += page.get_text()
#
#                print(f"Processing {filename}")
#
#                # Split the text into sections using "PAYMENT ADVICE"
#                invoice_sections = text.split("PAYMENT ADVICE")[1:]  # Ignore the first empty split
#
#                for section in invoice_sections:
#                    # Extract fields using regex
#                    file_data = {}
#                    for field, pattern in patterns.items():
#                        match = re.search(pattern, section, re.DOTALL)
#                        file_data[field] = match.group(1).strip() if match else None
#
#                    # Format the extracted data
#                    if file_data["Company Name"]:
#                        file_data["Company Name"] = " ".join(file_data["Company Name"].replace("\n", " ").split())
#
#                    if file_data["Invoice Date"]:
#                        try:
#                            date_obj = datetime.strptime(file_data["Invoice Date"], "%d %b %Y")
#                            file_data["Invoice Date"] = date_obj.strftime("%Y-%m-%d")
#                        except ValueError:
#                            print(f"Error parsing date for {filename}: {file_data['Invoice Date']}")
#
#                    # Check for duplicates
#                    combination = (file_data["Company Name"], file_data["Unit Price"])
#                    if combination in processed_combinations:
#                        print(f"Skipping duplicate invoice: {file_data['Invoice Number']} from {file_data['Company Name']}")
#                        continue
#
#                    # Store the extracted data
#                    extracted_data.setdefault(filename, []).append(file_data)
#                    processed_combinations.add(combination)
#                    print(combination)
#
#            except Exception as e:
#                print(f"Error processing {filename}: {e}")
#
#    # Post processing - insert into database
#    if extracted_data:
#        connection, cursor = db_conn()
#
#        for file, invoices in extracted_data.items():
#            for details in invoices:
#                try:
#                    store_type = 'Bar/Restaurant' if float(details['Unit Price']) >= 50.00 else 'Bottle Store'
#                    buyer = details['Company Name']
#                    print(f"Processed Invoice: Store Type - {store_type}, Company Name - {buyer}")
#
#                except Exception as e:
#                    print(f"Error processing invoice data for {file}: {e}")
#
#processed_data = update_buyers_table_from_pdf_data("./invoices")
