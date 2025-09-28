import sys
import json
from datetime import date
import datetime
import threading
import schedule
import time
from flask import Flask, render_template, redirect, url_for, request, send_file
import subprocess
from initialize import db_conn
from database_insert import insert_data
from flask import Flask, render_template, jsonify, redirect, request, session, url_for, Response, stream_with_context
import os
# Import xero client stuff here
from xero_python.api_client import ApiClient
from xero_python.accounting import AccountingApi
from xero_python.api_client.oauth2 import OAuth2Token
from xero_python.api_client.configuration import Configuration
from authlib.integrations.flask_client import OAuth
import requests
from xml.etree import ElementTree as ET
import io
import zipfile
import math
from config_loader import config

app = Flask(__name__)

# Configuration settings - now loaded from environment-specific config files
INVOICE_BUTTON_ENABLED = config.invoice_button_enabled

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/healthcheck')
def healthcheck():
    """Health check endpoint that verifies database connectivity"""
    try:
        # Test database connection
        connection, cursor = db_conn()
        
        # Run a simple PostgreSQL version query
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        
        # Close the connection
        cursor.close()
        connection.close()
        
        return {
            'status': 'healthy',
            'database': 'connected',
            'postgresql_version': version[0] if version else 'unknown',
            'timestamp': datetime.datetime.now().isoformat(),
            'environment': config.environment
        }, 200
        
    except Exception as e:
        return {
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e),
            'timestamp': datetime.datetime.now().isoformat(),
            'environment': config.environment
        }, 503

## Initialize Database Calls ##

# Function to call the main() function from initialize.py
def initialize_database():
    python_executable = sys.executable
    initialize_script = "initialize.py"
    result = subprocess.run([python_executable, initialize_script], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Initialize script failed with return code {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        raise Exception(f"Database initialization failed: {result.stderr}")
    else:
        print("✅ Database initialization completed successfully")
        print(f"Output: {result.stdout}")

@app.route('/initialize', methods=['POST'])
def initialize():
    print("Accessed /initialize route")
    try:
        initialize_database()
        return redirect(url_for('index'))
    except Exception as e:
        print(f"❌ Initialize failed: {e}")
        return f"Database initialization failed: {str(e)}", 500

# Process sales invoices + Xero routes
@app.route('/process-sales-invoices', methods=['POST'])
def process_sales_invoices():
    print("Accessed /process_sales_invoices route")
    process_sales_invoices_function()
    return redirect(url_for('index'))

def process_sales_invoices_function():
    python_executable = sys.executable
    process_sales_invoices_script = "sales_pdf_processor.py"
    subprocess.run([python_executable, process_sales_invoices_script])

# Configure the API client
oauth = OAuth(app)
app.secret_key = os.urandom(24)  # Required for session

# Define the Xero OAuth client (remote app setup)
open_id_config_url = 'https://identity.xero.com/.well-known/openid-configuration'
openid_config = requests.get(open_id_config_url).json()

xero = oauth.register(
    name="xero",
    version="2",
    client_id=config.xero_client_id,
    client_secret=config.xero_client_secret,
    endpoint_url="https://api.xero.com/",
    authorize_url="https://login.xero.com/identity/connect/authorize",
    access_token_url="https://identity.xero.com/connect/token",
    refresh_token_url="https://identity.xero.com/connect/token",
    scope="openid profile email accounting.contacts accounting.transactions accounting.settings accounting.attachments",  # Add any required scope here
    jwks_uri=openid_config['jwks_uri'],
)

def get_xero_tenant_id(access_token):
    url = "https://api.xero.com/connections"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        connections = response.json()
        if connections:
            # Assuming the user has at least one tenant, grab the first one
            tenant_id = connections[0]['tenantId']
            session['tenant_id'] = tenant_id  # Store tenant ID in session
            return tenant_id
        else:
            return None
    else:
        raise Exception(f"Error fetching tenant ID: {response.status_code} - {response.text}")

@app.route("/xerologin")
def xerologin():
    redirect_uri = url_for('xeroauth', _external=True)
    print(redirect_uri)
    return xero.authorize_redirect(redirect_uri)

@app.route("/xeroauth")
def xeroauth():
    # Authorize and get the access token
    token = xero.authorize_access_token()

    # Save the token in the session
    session['xero_token'] = token
    print(f"Token stored in session: {session['xero_token']}")

    # After storing the token, try to populate buyers
    try:
        populate_buyers()
        print("Successfully populated buyers from Xero")
        return redirect(url_for('invoices'))
    except Exception as e:
        print(f"Error populating buyers from Xero: {str(e)}")
       #Continue with the flow even if populate_buyers fails
    
    #return redirect(url_for('populate_buyers'))
    return redirect(url_for('invoices'))

def get_tenant_id(access_token):
    """Fetch the tenant ID using the access token"""
    headers = {
        'Authorization': f'Bearer {access_token}'
    }

    response = requests.get('https://api.xero.com/connections', headers=headers)

    if response.status_code == 200:
        connections = response.json()
        if connections:
            # Assuming the first tenant is the one you need
            return connections[0]['tenantId']
    else:
        return None

@app.route('/populate-buyers')
def populate_buyers():
    print("\n=== Starting populate_buyers() ===")
    from database_insert import update_data

    token = session.get('xero_token')
    if token is None:
        print("❌ No Xero token found in session")
        return redirect(url_for('xerologin'))
    else:
        print("✓ Xero session token found")

    tenant_id = get_tenant_id(token['access_token'])
    if not tenant_id:
        print("❌ Failed to retrieve Xero tenant ID")
        return "Could not retrieve Xero tenant ID.", 401
    print(f"✓ Retrieved tenant ID: {tenant_id}")

    # Fetch contacts from Xero API
    url = 'https://api.xero.com/api.xro/2.0/Contacts'
    headers = {
        'Authorization': f'Bearer {token["access_token"]}',
        'Xero-Tenant-Id': tenant_id,
        'Accept': 'application/xml'
    }
    print("Sending request to Xero API...")

    response = requests.get(url, headers=headers)
    print(f"API Response Status Code: {response.status_code}")
    if response.status_code != 200:
        print(f"❌ Error response from API: {response.text}")
        return f"Error fetching contacts: {response.status_code}", 400

    try:
        # Parse XML response
        print("Parsing XML response...")
        tree = ET.ElementTree(ET.fromstring(response.text))
        root = tree.getroot()
        print(f"✓ Found {len(root.findall('.//Contact'))} total contacts")

        connection, cursor = db_conn()
        print("✓ Database connection established")
        buyers_added = 0
        buyers_updated = 0

        customer_contacts = 0
        for contact in root.findall(".//Contact"):
            print("\n=== Processing Contact ===")
            # Print all available fields for the contact
            for element in contact:
                if element.text and element.text.strip():
                    print(f"{element.tag}: {element.text}")
                elif len(element) > 0:  # If element has child elements
                    print(f"\n{element.tag}:")
                    for child in element:
                        if child.text and child.text.strip():
                            print(f"  - {child.tag}: {child.text}")
                        # Handle nested structures like Addresses and Phones
                        elif len(child) > 0:
                            print(f"  {child.tag}:")
                            for subchild in child:
                                if subchild.text and subchild.text.strip():
                                    print(f"    - {subchild.tag}: {subchild.text}")

            # Check if contact is a customer
            is_customer = contact.find("IsCustomer")
            if is_customer is not None and is_customer.text.lower() == "true":
                print("\n✓ Found customer contact")
                customer_contacts += 1
                name = contact.find("Name").text
                firstname = contact.find("FirstName")
                firstname = firstname.text if firstname is not None else None
                lastname = contact.find("LastName")
                lastname = lastname.text if lastname is not None else None
                email = contact.find("EmailAddress")
                email = email.text if email is not None else None
                phone = contact.find("Phones/Phone/PhoneNumber")
                phone = phone.text if phone is not None else None
                phonecountrycode = contact.find("Phones/Phone/PhoneCountryCode")
                phonecountrycode = phonecountrycode.text if phonecountrycode is not None else None
                phoneareacode = contact.find("Phones/Phone/PhoneAreaCode")
                phoneareacode = phoneareacode.text if phoneareacode is not None else None
                address = contact.find(".//AddressLine1")
                address = address.text if address is not None else None

                print(f"\nProcessing buyer data:")
                print(f"Name: {name}")
                print(f"First name: {firstname}")
                print(f"Last name: {lastname}")
                print(f"Email: {email}")
                print(f"Phone: {phone}")
                print(f"Phone country code: {phonecountrycode}")
                print(f"Phone area code: {phoneareacode}")
                print(f"Address: {address}")

                # Check if buyer already exists
                cursor.execute("SELECT buyer FROM buyers WHERE buyer = %s", (name,))
                exists = cursor.fetchone()

                if exists:
                    print(f"Updating existing buyer: {name}")
                    update_data(table_name="buyers", condition={'buyer': name}, buyer=name, buyer_email=email, buyer_phone=f"{phonecountrycode}{phoneareacode}{phone}", buyer_address=address, primary_contact=f"{firstname} {lastname}")
                    cursor.execute("""
                        UPDATE buyers 
                        SET buyer_email = %s, buyer_phone = %s, buyer_address = %s
                        WHERE buyer = %s
                    """, (email, phone, address, name))
                    buyers_updated += 1
                else:
                    print(f"Adding new buyer: {name}")
                    insert_data(table_name="buyers", audit_action="Add buyer to buyers table", buyer=name, buyer_email=email, buyer_phone=f"{phonecountrycode}{phoneareacode}{phone}", buyer_address=address, primary_contact=f"{firstname} {lastname}")
                    buyers_added += 1

        print(f"\n=== Summary ===")
        print(f"Total contacts processed: {len(root.findall('.//Contact'))}")
        print(f"Customer contacts found: {customer_contacts}")
        print(f"New buyers added: {buyers_added}")
        print(f"Existing buyers updated: {buyers_updated}")

        connection.commit()
        cursor.close()
        connection.close()

        return f"Successfully added {buyers_added} new buyers and updated {buyers_updated} existing buyers."

    except ET.ParseError as e:
        print(f"❌ XML Parse Error: {str(e)}")
        print(f"Response content: {response.text[:200]}...")  # Print first 200 chars of response
        return f"Error: Invalid XML response from Xero API", 400
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return f"Error processing contacts: {str(e)}", 500

@app.route('/invoices')
def invoices():
    def generate_responses():
        # Get the saved token from the session
        token = session.get('xero_token')
        if token is None:
            yield "Redirecting to login...<br>\n"
            return redirect(url_for('xerologin'))
        else:
            yield "Xero session token acquired, searching for Xero tenant <br>\n"

        # Retrieve the tenant ID using the access token
        tenant_id = get_tenant_id(token['access_token'])
        if tenant_id is None:
            yield "Error: Unable to retrieve tenant ID.<br>\n"
            return
        else:
            yield "Xero tenant identified, processing invoices..<br>\n"

        # Start fetching invoices
        url = 'https://api.xero.com/api.xro/2.0/Invoices'
        headers = {
            'Authorization': f'Bearer {token["access_token"]}',
            'Xero-Tenant-Id': tenant_id,
            'Accept': 'application/xml',
        }

        yield "Fetching invoices from Xero API...<br>\n"
        yield f"API URL: {url}<br>\n"
        yield f"Headers: {headers}<br>\n"
        
        response = requests.get(url, headers=headers)
        yield f"Response status code: {response.status_code}<br>\n"
        yield f"Response headers: {dict(response.headers)}<br>\n"

        if response.status_code == 200:
            try:
                # Parse the XML response
                
                tree = ET.ElementTree(ET.fromstring(response.text))
                root = tree.getroot()
                yield f"Root element tag: {root.tag}<br>\n"
                yield f"Root element attributes: {root.attrib}<br>\n"

                # Find all invoice elements and filter by status
                all_invoices = root.findall(".//Invoice")
                yield f"Total invoices found in XML: {len(all_invoices)}<br>\n"
                
                invoices_data = []
                skipped_count = 0
                added_count = 0
                
                for i, invoice in enumerate(all_invoices):
                    try:
                        invoice_number = invoice.find("InvoiceNumber")
                        status = invoice.find("Status")
                        
                        if invoice_number is None:
                            yield f"WARNING: Invoice #{i+1} missing InvoiceNumber element<br>\n"
                            continue
                        if status is None:
                            yield f"WARNING: Invoice {invoice_number.text} missing Status element<br>\n"
                            continue
                            
                        invoice_num = invoice_number.text
                        invoice_status = status.text
                        
                        yield f"Processing invoice #{i+1}: {invoice_num} (Status: {invoice_status})<br>\n"
                        
                        if invoice_status not in ["AUTHORISED", "PAID"]:
                            yield f"SKIPPING: {invoice_num} - Status '{invoice_status}' not in allowed list<br>\n"
                            skipped_count += 1
                            continue
                        else:
                            yield f"ADDING: {invoice_num} - Status '{invoice_status}' is valid<br>\n"
                            added_count += 1

                        # Check for required fields
                        invoice_id = invoice.find("InvoiceID")
                        amount_due = invoice.find("AmountDue")
                        amount_paid = invoice.find("AmountPaid")
                        
                        if invoice_id is None or amount_due is None or amount_paid is None:
                            yield f"WARNING: {invoice_num} missing required fields - InvoiceID: {invoice_id is not None}, AmountDue: {amount_due is not None}, AmountPaid: {amount_paid is not None}<br>\n"
                            continue

                        invoice_data = {
                            "InvoiceID": invoice_id.text,
                            "InvoiceNumber": invoice_num,
                            "AmountDue": amount_due.text,
                            "AmountPaid": amount_paid.text,
                            "Status": invoice_status,
                        }
                        invoices_data.append(invoice_data)
                        
                    except Exception as e:
                        yield f"ERROR processing invoice #{i+1}: {str(e)}<br>\n"
                        continue
                
                yield f"<br>\nSUMMARY:<br>\n"
                yield f"- Total invoices in XML: {len(all_invoices)}<br>\n"
                yield f"- Invoices skipped: {skipped_count}<br>\n"
                yield f"- Invoices added: {added_count}<br>\n"
                yield f"- Final invoices_data list length: {len(invoices_data)}<br>\n"

                # Ensure the invoices directory exists
                invoices_dir = os.path.join(os.getcwd(), 'invoices')
                os.makedirs(invoices_dir, exist_ok=True)

                # Download PDFs for eligible invoices
                for invoice in invoices_data:
                    # Check if the invoice is already in the database
                    connection, cursor = db_conn()
                    cursor.execute("SELECT notes FROM sales_product WHERE notes LIKE %s", ('%' + invoice["InvoiceNumber"] + '%',))
                    data = cursor.fetchall()
                    print(data)
                    # Check if any of the returned notes contain the invoice number
                    invoice_exists = any(invoice["InvoiceNumber"] in note[0] for note in data)
                    if invoice_exists:
                        yield f"Invoice {invoice['InvoiceNumber']} already exists in the database.<br>\n"
                        continue
                    else:
                        invoice_id = invoice["InvoiceID"]
                    pdf_url = f'https://api.xero.com/api.xro/2.0/Invoices/{invoice_id}'
                    pdf_headers = {
                        'Authorization': f'Bearer {token["access_token"]}',
                        'Xero-Tenant-Id': tenant_id,
                        'Accept': 'application/pdf',
                    }

                    pdf_response = requests.get(pdf_url, headers=pdf_headers)

                    if pdf_response.status_code == 200:
                        pdf_filename = os.path.join(invoices_dir, f"{invoice['InvoiceNumber']}.pdf")
                        with open(pdf_filename, 'wb') as pdf_file:
                            pdf_file.write(pdf_response.content)
                        yield f"Downloaded and saved {pdf_filename}.<br>\n"
                    else:
                        yield (f"Error downloading PDF for invoice {invoice_id} (Number: {invoice['InvoiceNumber']}). "
                               f"Status Code: {pdf_response.status_code}, Response: {pdf_response.text}<br>\n")

                # Trigger the /process-sales-invoices route
                yield "Processing sales invoices...<br>\n"
                with app.test_request_context():
                    process_sales_invoices_function()
                yield "Processed sales invoices.<br>\n"

            except ET.ParseError:
                yield f"Error: The response from Xero API is not in valid XML format. Raw response: {response.text}<br>\n"
                return
        else:
            yield f"Error: Received {response.status_code} response from Xero API: {response.text}<br>\n"
            return

        yield """
        <html>
            <head>
                <meta http-equiv="refresh" content="3; url=/" />
            </head>
            <body>
                <p>Task completed! You will be redirected to the homepage in 3 seconds.</p>
            </body>
        </html>
        """

    # Stream the response to the client
    return Response(stream_with_context(generate_responses()), content_type='text/html')

def validate_xero_token():
    """
    Validates the Xero token and handles token refresh if needed.
    Returns:
        tuple: (is_valid, token, tenant_id)
        - is_valid: boolean indicating if we have a valid token
        - token: the token object if valid, None otherwise
        - tenant_id: the tenant ID if valid, None otherwise
    """
    token = session.get('xero_token')
    if token is None:
        print("❌ No Xero token found in session")
        return False, None, None

    try:
        # Check if token is expired
        if token.get('expires_at', 0) < time.time():
            print("Token expired, attempting to refresh...")
            try:
                # Try to refresh the token
                new_token = xero.refresh_token(token['refresh_token'])
                session['xero_token'] = new_token
                token = new_token
                print("✓ Token refreshed successfully")
            except Exception as e:
                print(f"❌ Failed to refresh token: {str(e)}")
                return False, None, None

        # Verify token by getting tenant ID
        tenant_id = get_tenant_id(token['access_token'])
        if not tenant_id:
            print("❌ Failed to retrieve Xero tenant ID")
            return False, None, None

        print("✓ Valid Xero token found")
        return True, token, tenant_id

    except Exception as e:
        print(f"❌ Error validating token: {str(e)}")
        return False, None, None

@app.route('/sync-xero-data', methods=['POST', 'GET'])
def sync_xero_data():
    print("\n=== Starting Xero data sync ===")
    
    # Get the current run count from session, default to 0 if not exists
    run_count = session.get('sync_run_count', 0)
    
    # Validate token
    is_valid, token, tenant_id = validate_xero_token()
    if not is_valid:
        print("❌ Invalid or expired token, redirecting to login")
        session['sync_run_count'] = 0  # Reset counter on invalid token
        return redirect(url_for('xerologin'))
    
    if run_count == 0:
        # First run - get/refresh token and run initial functions
        print("First run - processing initial functions...")
        try:
            print("Processing invoices from Xero...")
            process_sales_invoices_function()
            print("Successfully processed invoices from Xero")
        except Exception as e:
            print(f"Error processing invoices from Xero: {str(e)}")
        
        # Increment run count and store in session
        session['sync_run_count'] = 1
        # Redirect to same route to trigger second run
        return redirect(url_for('sync_xero_data'))
    
    else:
        # Second run - run remaining functions
        print("Second run - processing remaining functions...")
        try:
            print("Populating buyers from Xero...")
            populate_buyers()
            print("Successfully populated buyers from Xero")
        except Exception as e:
            print(f"Error populating buyers from Xero: {str(e)}")
        
        # Reset run count
        session['sync_run_count'] = 0
        return redirect(url_for('index'))

@app.route('/back-button', methods=['POST'])
def back_button():
    print("Accessed /back-button route")

    return redirect(url_for('index'))

@app.route('/back-button-data-tools', methods=['POST'])
def back_button_data_tools():
    print("Accessed /back-button-data-tools route")

    return render_template('data_tools.html')

@app.route('/back-button-audit-tools', methods=['POST'])
def back_button_audit_tools():
    print("Accessed /back-button-audit-tools route")

    return render_template('audit_tools.html')

@app.route('/back-button-database-query-form', methods=['POST'])
def back_button_database_query_form():
    print("Accessed /back-button-database-query-form route")

    return render_template('database_query_form.html')

@app.route('/back-button-product-tools', methods=['POST'])
def back_button_product_tools():
    print("Accessed /back-button-product-tools route")

    return render_template('product_tools.html')

@app.route('/back-button-buys-sells', methods=['POST'])
def back_button_buys_sells():
    print("Accessed /back-button-buys-sells route")

    return render_template('buys_sells.html')

@app.route('/back-button-calculations', methods=['POST'])
def back_button_calculations():
    print("Accessed /back-button-calculations route")

    return render_template('calculations.html')

@app.route('/back-button-audit-data', methods=['POST'])
def back_button_audit_data():
    print("Accessed /back-button-audit-data route")

    return render_template('raw_data.html')

@app.route('/data-tools', methods=['POST'])
def data_tools():
    print("Accessed /data-tools route")

    return render_template('data_tools.html')

@app.route('/audit-tools', methods=['POST'])
def audit_tools():
    print("Accessed /audit-tools route")

    return render_template('audit_tools.html')

@app.route('/product-tools', methods=['POST'])
def product_tools():
    print("Accessed /product-tools route")

    return render_template('product_tools.html')

@app.route('/buys-sells', methods=['POST'])
def buys_sells():
    print("Accessed /buys-sells route")

    return render_template('buys_sells.html')

@app.route('/calculation-tools', methods=['POST'])
def calculation_tools():
    print("Accessed /calculation-tools route")

    return render_template('calculations.html')

@app.route('/rawdata', methods=['POST'])
def raw_data():
    # Get data from the database
    print("Accessed /rawdata route")
    from data_fetch import raw_data
    data = raw_data()
    return render_template('raw_data.html', data=data)

@app.route('/inventory', methods=['POST'])
def inventory():
    # Get data from the database
    print("Accessed /inventory route")
    from data_fetch import inventory
    data = inventory()
    inventory()

    return render_template('inventory.html', data=data)

@app.route('/monthly-totals', methods=['POST'])
def monthly_totals():
    print("Accessed /monthly-totals route")
    from data_fetch import monthly_totals
    data = monthly_totals()

    monthly_totals()

    return render_template('monthly_totals.html', data=data)

@app.route('/crm', methods=['GET', 'POST'])
def crm():
    print("Accessed /crm route")
    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Auto-sync any missing customers from sales data before loading CRM
        print("Checking for missing customers and auto-syncing...")
        potential_matches = auto_sync_missing_customers()
        
        # Get all customers from CRM system (existing + potential)
        cursor.execute("""
            SELECT DISTINCT customer, customer_email, customer_phone, customer_address, primary_contact
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
            ORDER BY customer
        """)
        existing_customer_info = cursor.fetchall()

        # Get existing customers with sales (for statistics)
        cursor.execute("""
            SELECT DISTINCT b.buyer 
            FROM buyers b
            INNER JOIN sales_product sp ON b.buyer = sp.buyer 
            ORDER BY b.buyer
        """)
        existing_customers = cursor.fetchall()

        # Get active customers this month (from sales data)
        cursor.execute("""
            SELECT COUNT(DISTINCT buyer) FROM sales_product WHERE date_trunc('month', date) = date_trunc('month', CURRENT_DATE)
        """)
        active_customers_this_month = cursor.fetchall()

        # Get detailed active customers this month with product breakdown
        cursor.execute("""
            WITH customer_stats AS (
                SELECT 
                    b.buyer, 
                    b.buyer_email, 
                    b.primary_contact, 
                    b.buyer_phone,
                    COUNT(sp.date) as purchase_count,
                    SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(sp.products->'products'))) as total_bottles,
                    MAX(sp.date) as latest_purchase_date,
                    MIN(sp.date) as first_purchase_this_month
                FROM buyers b
                INNER JOIN sales_product sp ON b.buyer = sp.buyer
                WHERE date_trunc('month', sp.date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY b.buyer, b.buyer_email, b.primary_contact, b.buyer_phone
            ),
            product_breakdown AS (
                SELECT 
                    sp.buyer,
                    jsonb_agg(
                        jsonb_build_object(
                            'product_name', p.key,
                            'quantity', COALESCE((p.value->>'quantity')::int, 0),
                            'unit_price', COALESCE((p.value->>'unit_price')::numeric, 0),
                            'date', sp.date
                        ) ORDER BY sp.date DESC
                    ) as products
                FROM sales_product sp,
                     jsonb_each(sp.products->'products') AS p(key, value)
                WHERE date_trunc('month', sp.date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY sp.buyer
            )
            SELECT 
                cs.buyer,
                cs.buyer_email,
                cs.primary_contact,
                cs.buyer_phone,
                cs.purchase_count,
                cs.total_bottles,
                cs.latest_purchase_date,
                cs.first_purchase_this_month,
                COALESCE(pb.products, '[]'::jsonb) as product_details
            FROM customer_stats cs
            LEFT JOIN product_breakdown pb ON cs.buyer = pb.buyer
            ORDER BY cs.total_bottles DESC, cs.latest_purchase_date DESC
        """)
        active_customers_details = cursor.fetchall()

        # Get new customers this month (from sales data)
        cursor.execute("""
            WITH first_purchases AS (
                SELECT
                    buyer,
                    MIN(date) as first_purchase_date
                FROM sales_product
                WHERE notes LIKE '%INV%'
                GROUP BY buyer
            )
            SELECT
                COUNT(buyer)
            FROM first_purchases
            WHERE date_trunc('month', first_purchase_date) = date_trunc('month', CURRENT_DATE)
            """)
        new_customers_this_month = cursor.fetchall()

        # Get detailed new customers this month with product breakdown
        cursor.execute("""
            WITH first_purchases AS (
                SELECT
                    buyer,
                    MIN(date) as first_purchase_date
                FROM sales_product
                WHERE notes LIKE '%INV%'
                GROUP BY buyer
            ),
            new_customer_stats AS (
                SELECT 
                    b.buyer, 
                    b.buyer_email, 
                    b.primary_contact, 
                    b.buyer_phone,
                    fp.first_purchase_date,
                    COUNT(sp.date) as purchase_count,
                    SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(sp.products->'products'))) as total_bottles,
                    MAX(sp.date) as latest_purchase_date
                FROM buyers b
                INNER JOIN first_purchases fp ON b.buyer = fp.buyer
                INNER JOIN sales_product sp ON b.buyer = sp.buyer
                WHERE date_trunc('month', fp.first_purchase_date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY b.buyer, b.buyer_email, b.primary_contact, b.buyer_phone, fp.first_purchase_date
            ),
            product_breakdown AS (
                SELECT 
                    sp.buyer,
                    jsonb_agg(
                        jsonb_build_object(
                            'product_name', p.key,
                            'quantity', COALESCE((p.value->>'quantity')::int, 0),
                            'unit_price', COALESCE((p.value->>'unit_price')::numeric, 0),
                            'date', sp.date
                        ) ORDER BY sp.date DESC
                    ) as products
                FROM sales_product sp
                INNER JOIN first_purchases fp ON sp.buyer = fp.buyer,
                     jsonb_each(sp.products->'products') AS p(key, value)
                WHERE date_trunc('month', fp.first_purchase_date) = date_trunc('month', CURRENT_DATE)
                AND sp.notes LIKE '%INV%'
                GROUP BY sp.buyer
            )
            SELECT 
                ncs.buyer,
                ncs.buyer_email,
                ncs.primary_contact,
                ncs.buyer_phone,
                ncs.first_purchase_date,
                ncs.purchase_count,
                ncs.total_bottles,
                ncs.latest_purchase_date,
                COALESCE(pb.products, '[]'::jsonb) as product_details
            FROM new_customer_stats ncs
            LEFT JOIN product_breakdown pb ON ncs.buyer = pb.buyer
            ORDER BY ncs.first_purchase_date DESC, ncs.total_bottles DESC
        """)
        new_customers_details = cursor.fetchall()

        # Get customers needing follow-ups (from sales data)
        cursor.execute("""
            WITH buyer_stats AS (
                    SELECT
                        buyer,
                        date,
                        bottles_sold,
                        MAX(date) OVER (PARTITION BY buyer) AS latest_date,
                        SUM(bottles_sold) OVER (PARTITION BY buyer) AS total_bottles_sold,
                        COUNT(CASE WHEN notes ILIKE '%Sample%' THEN 1 END) OVER (PARTITION BY buyer) AS sample_notes_count,
                        COUNT(notes) OVER (PARTITION BY buyer) AS total_notes_count,
                        FIRST_VALUE(bottles_sold) OVER (PARTITION BY buyer ORDER BY date DESC) as recent_bottles_sold,
                        FIRST_VALUE(unit_price) OVER (PARTITION BY buyer ORDER BY date DESC) as unit_price, product_name
                    FROM sales_product
                    WHERE notes LIKE '%INV%'  -- Only consider invoice sales
                )
                SELECT DISTINCT b.buyer, b.buyer_email, b.primary_contact, b.buyer_phone,
                       bs.latest_date, bs.total_bottles_sold, bs.recent_bottles_sold, bs.unit_price, bs.product_name
                FROM buyers b
                JOIN (
                    SELECT DISTINCT ON (buyer)
                        buyer, latest_date, total_bottles_sold, recent_bottles_sold, unit_price,
                        sample_notes_count, total_notes_count, product_name
                    FROM buyer_stats
                    ORDER BY buyer, latest_date DESC
                ) bs ON b.buyer = bs.buyer
                WHERE (
                    (bs.latest_date < CURRENT_DATE - INTERVAL '1 weeks' AND bs.total_bottles_sold < 2)
                    OR
                    (bs.latest_date < CURRENT_DATE - INTERVAL '2 weeks' AND bs.total_bottles_sold < 3)
                    OR
                    (bs.latest_date < CURRENT_DATE - INTERVAL '3 weeks' AND bs.total_bottles_sold < 4)
                    OR
                    bs.latest_date < CURRENT_DATE - INTERVAL '4 weeks'
                )
                AND b.buyer != 'WHISTLEBIRD INTERNAL (Personal)'
                AND (bs.sample_notes_count < bs.total_notes_count OR bs.sample_notes_count = 0)
                ORDER BY bs.latest_date
        """)
        existing_customer_follow_ups = cursor.fetchall()

        # Get follow-ups due from crm_follow_ups table
        cursor.execute("""
                SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
                FROM crm_follow_ups
                WHERE follow_up_status != 'completed'
                ORDER BY 
                    CASE 
                        WHEN follow_up_date IS NULL THEN 1
                        ELSE 0
                    END,
                    follow_up_date ASC
        """)
        follow_ups_due = cursor.fetchall()

        # Parse JSONB data for active customers
        parsed_active_customers = []
        for customer in active_customers_details:
            customer_list = list(customer)
            if len(customer_list) > 8 and customer_list[8]:
                try:
                    import json
                    if isinstance(customer_list[8], str):
                        customer_list[8] = json.loads(customer_list[8])
                except (json.JSONDecodeError, TypeError):
                    customer_list[8] = []
            parsed_active_customers.append(tuple(customer_list))

        # Parse JSONB data for new customers
        parsed_new_customers = []
        for customer in new_customers_details:
            customer_list = list(customer)
            if len(customer_list) > 8 and customer_list[8]:
                try:
                    import json
                    if isinstance(customer_list[8], str):
                        customer_list[8] = json.loads(customer_list[8])
                except (json.JSONDecodeError, TypeError):
                    customer_list[8] = []
            parsed_new_customers.append(tuple(customer_list))

        print(f"CRM loaded: {len(existing_customer_info)} total customers, {len(existing_customers)} with sales, {len(follow_ups_due)} follow-ups due")

        return render_template('crm.html', 
                            existing_customers=existing_customers, 
                            existing_customer_info=existing_customer_info, 
                            active_customers_this_month=active_customers_this_month, 
                            active_customers_details=parsed_active_customers,
                            new_customers_this_month=new_customers_this_month, 
                            new_customers_details=parsed_new_customers,
                            existing_customer_follow_ups=existing_customer_follow_ups,
                            follow_ups_due=follow_ups_due,
                            potential_matches=potential_matches)
    
    except Exception as e:
        print(f"Error in CRM route: {e}")
        return render_template('crm.html', 
                            existing_customers=[],
                            existing_customer_info=[],
                            active_customers_this_month=[],
                            active_customers_details=[],
                            new_customers_this_month=[],
                            new_customers_details=[],
                            existing_customer_follow_ups=[],
                            follow_ups_due=[],
                            potential_matches=[])
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def auto_sync_missing_customers():
    """Automatically sync any customers that exist in sales data but not in CRM"""
    print("Starting auto-sync of missing customers...")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    try:
        # Get existing customers from CRM with case-insensitive comparison
        cursor.execute("""
            SELECT DISTINCT LOWER(customer) as customer_lower, customer
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
        """)
        crm_customers = cursor.fetchall()
        crm_customer_names_lower = [customer[0] for customer in crm_customers]
        crm_customer_names_original = [customer[1] for customer in crm_customers]
        print(f"Found {len(crm_customer_names_original)} existing customers in CRM")

        # Get customers from sales data with case-insensitive comparison
        cursor.execute("""
            SELECT DISTINCT LOWER(buyer) as buyer_lower, buyer
            FROM sales_product
            WHERE buyer IS NOT NULL AND buyer != '' AND buyer != 'WHISTLEBIRD INTERNAL (Personal)'
            AND notes LIKE '%INV%'
        """)
        sales_customers = cursor.fetchall()
        sales_customer_names_lower = [customer[0] for customer in sales_customers]
        sales_customer_names_original = [customer[1] for customer in sales_customers]
        print(f"Found {len(sales_customer_names_original)} customers in sales data")
        
        # Debug: Show a sample of what's in the buyers table for comparison
        print(f"\nDebug: Checking buyers table structure...")
        cursor.execute("""
            SELECT COUNT(*) as total_buyers
            FROM buyers
            WHERE buyer IS NOT NULL AND buyer != ''
        """)
        total_buyers = cursor.fetchone()[0]
        print(f"Total buyers in buyers table: {total_buyers}")

        # Get all existing customers with their aliases for comprehensive checking
        cursor.execute("""
            SELECT customer, aliases
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
        """)
        customers_with_aliases = cursor.fetchall()
        
        # Build a comprehensive list of all customer names and aliases (lowercase for comparison)
        all_existing_names_lower = set()
        for customer, aliases in customers_with_aliases:
            all_existing_names_lower.add(customer.lower())
            if aliases:
                for alias in aliases:
                    all_existing_names_lower.add(alias.lower())
        
        print(f"Total existing customer names and aliases: {len(all_existing_names_lower)}")
        
        # Find missing customers using case-insensitive comparison against all names and aliases
        missing_customers = []
        for i, customer_name_lower in enumerate(sales_customer_names_lower):
            if customer_name_lower not in all_existing_names_lower:
                missing_customers.append(sales_customer_names_original[i])

        print(f"Found {len(missing_customers)} customers to auto-sync")

        # Check for potential duplicate matches using word-based similarity
        # Also check against existing aliases
        potential_matches = []
        for missing_customer in missing_customers:
            missing_words = set(missing_customer.lower().split())
            if len(missing_words) >= 2:  # Only check customers with 2+ words
                customer_matches = []
                
                for existing_customer, aliases in customers_with_aliases:
                    # Check similarity with main customer name
                    existing_words = set(existing_customer.lower().split())
                    common_words = missing_words.intersection(existing_words)
                    total_unique_words = missing_words.union(existing_words)
                    similarity = len(common_words) / len(total_unique_words) if total_unique_words else 0
                    
                    # Also check against aliases if they exist
                    if aliases:
                        for alias in aliases:
                            alias_words = set(alias.lower().split())
                            alias_common_words = missing_words.intersection(alias_words)
                            alias_total_words = missing_words.union(alias_words)
                            alias_similarity = len(alias_common_words) / len(alias_total_words) if alias_total_words else 0
                            similarity = max(similarity, alias_similarity)
                    
                    # Flag as potential match if 60%+ word similarity and at least 2 common words
                    if similarity >= 0.6 and len(common_words) >= 2:
                        customer_matches.append({
                            'existing_customer': existing_customer,
                            'similarity': similarity,
                            'common_words': list(common_words)
                        })
                
                # Sort matches by similarity (highest first)
                customer_matches.sort(key=lambda x: x['similarity'], reverse=True)
                
                if customer_matches:
                    potential_matches.append({
                        'new_customer': missing_customer,
                        'matches': customer_matches[:5]  # Limit to top 5 matches
                    })
        
        # Remove potential matches from missing customers list
        potential_match_names = [match['new_customer'] for match in potential_matches]
        safe_to_sync = [customer for customer in missing_customers if customer not in potential_match_names]
        
        print(f"Found {len(potential_matches)} potential duplicate matches")
        print(f"Found {len(safe_to_sync)} customers safe to auto-sync")
        
        # Debug: Show the list of customers we're about to process
        print(f"\nCustomers to process:")
        for i, customer in enumerate(safe_to_sync, 1):
            print(f"  {i}. '{customer}'")
        
        # Debug: Show potential matches that were found
        if potential_matches:
            print(f"\nPotential matches found (requires manual review):")
            for i, match in enumerate(potential_matches, 1):
                print(f"  {i}. '{match['new_customer']}' has {len(match['matches'])} potential matches:")
                for j, potential_match in enumerate(match['matches'], 1):
                    print(f"    {j}. '{potential_match['existing_customer']}' ({potential_match['similarity']:.1%} similarity)")

        # Sync safe customers
        synced_count = 0
        for customer_name in safe_to_sync:
            print(f"\n--- Processing customer: {customer_name} ---")
            try:
                # Debug: Show the exact SQL query being executed
                sql_query = """
                    SELECT DISTINCT(buyer), buyer_email, buyer_phone, buyer_address, primary_contact
                    FROM buyers
                    WHERE LOWER(buyer) = LOWER(%s)
                """
                print(f"Executing SQL: {sql_query.strip()}")
                print(f"With parameter: '{customer_name}'")
                
                # Get customer details from buyers table with case-insensitive comparison
                cursor.execute(sql_query, (customer_name,))
                buyer_data = cursor.fetchone()
                
                print(f"SQL result: {buyer_data}")
                
                if buyer_data:
                    buyer, buyer_email, buyer_phone, buyer_address, primary_contact = buyer_data
                    print(f"Found buyer data: {buyer}")
                    
                    # Insert missing customer into crm_customers table
                    insert_data(table_name='crm_customers',
                                audit_action='Auto-syncing Customer from Sales Data',
                                customer=buyer,
                                customer_email=buyer_email,
                                customer_phone=buyer_phone,
                                customer_address=buyer_address,
                                primary_contact=primary_contact)
                    
                    print(f"✓ Auto-synced customer: {buyer}")
                    synced_count += 1
                else:
                    print(f"⚠ Warning: No data found for customer {customer_name} in buyers table")
                    
                    # Debug: Let's check what's actually in the buyers table for this customer
                    print(f"Debug: Checking buyers table for variations of '{customer_name}'")
                    
                    # Try a broader search to see what's in the buyers table
                    cursor.execute("""
                        SELECT DISTINCT buyer 
                        FROM buyers 
                        WHERE LOWER(buyer) LIKE LOWER(%s)
                        ORDER BY buyer
                    """, (f'%{customer_name}%',))
                    similar_buyers = cursor.fetchall()
                    print(f"Debug: Found {len(similar_buyers)} similar buyers:")
                    for similar in similar_buyers:
                        print(f"  - '{similar[0]}'")
                    
                    # Check if this is a case where the sales name is a subset of a buyers name
                    # (e.g., "R&D 2007 LIMITED" vs "R&D 2007 LIMITED (CENTRE CITY WINES & SPIRITS)")
                    potential_extended_matches = []
                    for similar_buyer in similar_buyers:
                        similar_name = similar_buyer[0]
                        # Check if the sales customer name is contained within the buyers name
                        if customer_name.lower() in similar_name.lower():
                            potential_extended_matches.append(similar_name)
                    
                    if potential_extended_matches:
                        print(f"⚠ Found potential extended name matches for '{customer_name}':")
                        for match in potential_extended_matches:
                            print(f"  - '{match}' (contains '{customer_name}')")
                        
                        # Add these to potential matches for manual review
                        extended_matches = []
                        for match in potential_extended_matches:
                            extended_matches.append({
                                'existing_customer': match,
                                'similarity': 0.9,  # High similarity since it's a subset
                                'common_words': [customer_name.lower()]
                            })
                        
                        # Check if this customer already has potential matches
                        existing_potential_match = None
                        for pm in potential_matches:
                            if pm['new_customer'] == customer_name:
                                existing_potential_match = pm
                                break
                        
                        if existing_potential_match:
                            # Add to existing matches
                            existing_potential_match['matches'].extend(extended_matches)
                            existing_potential_match['matches'].sort(key=lambda x: x['similarity'], reverse=True)
                        else:
                            # Create new potential match entry
                            potential_matches.append({
                                'new_customer': customer_name,
                                'matches': extended_matches
                            })
                        
                        print(f"  → Added to potential matches for manual review")
                    
                    # Also try searching by individual words
                    words = customer_name.lower().split()
                    if len(words) >= 2:
                        print(f"Debug: Searching by individual words: {words}")
                        for word in words:
                            if len(word) > 2:  # Only search for words longer than 2 characters
                                cursor.execute("""
                                    SELECT buyer 
                                    FROM buyers 
                                    WHERE LOWER(buyer) LIKE LOWER(%s)
                                    ORDER BY buyer
                                """, (f'%{word}%',))
                                word_matches = cursor.fetchall()
                                if word_matches:
                                    print(f"  Word '{word}' matches:")
                                    for match in word_matches[:5]:  # Limit to first 5 matches
                                        print(f"    - '{match[0]}'")
                    
            except Exception as e:
                print(f"❌ Error auto-syncing customer {customer_name}: {e}")
                continue
        
        print(f"Successfully auto-synced {synced_count} out of {len(safe_to_sync)} safe customers")
        
        return potential_matches
        
    except Exception as e:
        print(f"❌ Error in auto_sync_missing_customers: {e}")
        if connection:
            connection.rollback()
        return []
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/crm-handle-potential-match', methods=['POST'])
def crm_handle_potential_match():
    """Handle potential duplicate customer matches from modal"""
    print("Accessed /crm-handle-potential-match route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    action = data.get("action")  # "alias" or "create_new"
    new_customer_name = data.get("new_customer_name")
    existing_customer_name = data.get("existing_customer_name")
    
    try:
        if action == "alias":
            # Add new_customer_name as alias to existing_customer_name
            print(f"Adding '{new_customer_name}' as alias to '{existing_customer_name}'")
            
            # Get current aliases for the existing customer
            cursor.execute("""
                SELECT aliases FROM crm_customers 
                WHERE customer = %s
            """, (existing_customer_name,))
            result = cursor.fetchone()
            
            current_aliases = result[0] if result and result[0] else []
            
            # Add the new alias if it's not already there
            if new_customer_name not in current_aliases:
                current_aliases.append(new_customer_name)
                
                # Update the aliases array
                cursor.execute("""
                    UPDATE crm_customers 
                    SET aliases = %s 
                    WHERE customer = %s
                """, (current_aliases, existing_customer_name))
                
                connection.commit()
                print(f"✓ Added '{new_customer_name}' as alias to '{existing_customer_name}'")
                return jsonify({
                    "success": True, 
                    "message": f"'{new_customer_name}' added as alias to '{existing_customer_name}'"
                })
            else:
                return jsonify({
                    "success": True, 
                    "message": f"'{new_customer_name}' is already an alias for '{existing_customer_name}'"
                })
        
        elif action == "create_new":
            # Create new customer entry
            print(f"Creating new customer: {new_customer_name}")
            
            # Get customer details from buyers table
            cursor.execute("""
                SELECT buyer, buyer_email, buyer_phone, buyer_address, primary_contact
                FROM buyers
                WHERE LOWER(buyer) = LOWER(%s)
            """, (new_customer_name,))
            buyer_data = cursor.fetchone()
            
            if buyer_data:
                buyer, buyer_email, buyer_phone, buyer_address, primary_contact = buyer_data
                
                # Insert customer into crm_customers table
                insert_data(table_name='crm_customers',
                            audit_action='Manual Creation of New Customer',
                            customer=buyer,
                            customer_email=buyer_email,
                            customer_phone=buyer_phone,
                            customer_address=buyer_address,
                            primary_contact=primary_contact)
                
                print(f"✓ Created new customer: {buyer}")
                return jsonify({"success": True, "message": f"Customer {buyer} created successfully"})
            else:
                return jsonify({"success": False, "message": f"No data found for customer {new_customer_name}"})
        
        else:
            return jsonify({"success": False, "message": "Invalid action"})
            
    except Exception as e:
        print(f"❌ Error handling potential match: {e}")
        if connection:
            connection.rollback()
        return jsonify({"success": False, "message": f"Error: {str(e)}"})
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/crm-add-alias', methods=['POST'])
def crm_add_alias():
    """Add an alias to a customer"""
    print("Accessed /crm-add-alias route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    customer_name = data.get("customer_name")
    alias_name = data.get("alias_name")
    
    try:
        if not customer_name or not alias_name:
            return jsonify({"success": False, "message": "Customer name and alias name are required"})
        
        # Get current aliases for the customer
        cursor.execute("""
            SELECT aliases FROM crm_customers 
            WHERE customer = %s
        """, (customer_name,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({"success": False, "message": f"Customer '{customer_name}' not found"})
        
        current_aliases = result[0] if result[0] else []
        
        # Check if alias already exists
        if alias_name in current_aliases:
            return jsonify({"success": False, "message": f"Alias '{alias_name}' already exists for this customer"})
        
        # Add the new alias
        current_aliases.append(alias_name)
        
        # Update the aliases array
        cursor.execute("""
            UPDATE crm_customers 
            SET aliases = %s 
            WHERE customer = %s
        """, (current_aliases, customer_name))
        
        connection.commit()
        print(f"✓ Added alias '{alias_name}' to customer '{customer_name}'")
        return jsonify({
            "success": True, 
            "message": f"Alias '{alias_name}' added successfully"
        })
        
    except Exception as e:
        print(f"❌ Error adding alias: {e}")
        if connection:
            connection.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/crm-remove-alias', methods=['POST'])
def crm_remove_alias():
    """Remove an alias from a customer"""
    print("Accessed /crm-remove-alias route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    customer_name = data.get("customer_name")
    alias_name = data.get("alias_name")
    
    try:
        if not customer_name or not alias_name:
            return jsonify({"success": False, "message": "Customer name and alias name are required"})
        
        # Get current aliases for the customer
        cursor.execute("""
            SELECT aliases FROM crm_customers 
            WHERE customer = %s
        """, (customer_name,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({"success": False, "message": f"Customer '{customer_name}' not found"})
        
        current_aliases = result[0] if result[0] else []
        
        # Check if alias exists
        if alias_name not in current_aliases:
            return jsonify({"success": False, "message": f"Alias '{alias_name}' not found for this customer"})
        
        # Remove the alias
        current_aliases.remove(alias_name)
        
        # Update the aliases array
        cursor.execute("""
            UPDATE crm_customers 
            SET aliases = %s 
            WHERE customer = %s
        """, (current_aliases, customer_name))
        
        connection.commit()
        print(f"✓ Removed alias '{alias_name}' from customer '{customer_name}'")
        return jsonify({
            "success": True, 
            "message": f"Alias '{alias_name}' removed successfully"
        })
        
    except Exception as e:
        print(f"❌ Error removing alias: {e}")
        if connection:
            connection.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/crm-create-customer', methods=['POST'])
def crm_create_customer():
    print("Accessed /crm-create-customer route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    data = request.get_json()
    customer_name = data.get("customer_name")
    customer_email = data.get("customer_email")
    customer_phone = data.get("customer_phone")
    customer_address = data.get("customer_address")
    primary_contact = data.get("primary_contact")
    customer_converted = data.get("customer_converted")
    customer_last_contact = datetime.date.today()
    customer_notes = data.get("customer_notes")

    # Insert customer into crm_customer table
    insert_data(table_name='crm_customers', audit_action='Create new CRM Customer', customer=customer_name, primary_contact=primary_contact, customer_address=customer_address, customer_phone=customer_phone, customer_email=customer_email, customer_status=customer_converted, customer_last_contact=customer_last_contact, customer_notes=customer_notes)

    # Fetch and insert follow-up task only if checkbox is checked
    if data.get("add_follow_up") == "yes":
        follow_up_task = data.get("follow_up_task")
        follow_up_date = data.get("follow_up_date")
        follow_up_priority = data.get("follow_up_priority")
        follow_up_type = data.get("follow_up_type")
        follow_up_status = data.get("follow_up_status")

        # Insert follow-up task into crm_follow_ups table
        insert_data(table_name='crm_follow_ups', audit_action='Create Follow-up Tasks', customer=customer_name, follow_up_date=follow_up_date, follow_up_priority=follow_up_priority, follow_up_status=follow_up_status, follow_up_notes=follow_up_task, follow_up_type=follow_up_type)
    
    return jsonify({
        "success": True,
        "message": "Customer created successfully",
        "redirect_url": customer_page_redirect_response(customer_name)
    })

def customer_page_redirect_response(customer_name):
    """
    Helper function to create a standardized redirect URL for customer page.
    Can be called from multiple places in the CRM.
    """
    return f"/crm-customer-page?customer_name={customer_name}"

@app.route('/crm-customer-page', methods=['GET', 'POST'])
def crm_customer_page():
    print("Accessed /crm-customer-page route")
    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        print("Starting customer page load...")
        
        # Handle both GET (from URL) and POST (from form) data
        if request.method == 'POST':
            if request.is_json:
                data = request.get_json()
                customer_name = data.get("customer_name")
            else:
                customer_name = request.form.get("customer_name")
        else:
            # GET request - get customer name from URL parameters
            customer_name = request.args.get("customer_name")
        
        print(f"Customer name received: {customer_name}")
        
        if not customer_name:
            print("No customer name provided")
            return render_template('customer_detail.html', 
                                customer_info=None, 
                                follow_up_tasks=None, 
                                customer_invoice_data=None,
                                call_logs=None,
                                invoice_button_enabled=INVOICE_BUTTON_ENABLED,
                                error_message="No customer name provided")

        # Fetch customer information from crm_customers table
        print(f"Fetching customer info for: {customer_name}")
        cursor.execute("""
            SELECT customer, customer_email, customer_phone,
            customer_address, primary_contact, customer_status, customer_last_contact, customer_notes, aliases, contacts
            FROM crm_customers WHERE customer = %s
        """, (customer_name,))
        customer_info = cursor.fetchall()
        
        print(f"Customer info found: {len(customer_info)} records")
        
        # If customer doesn't exist in CRM, try to sync them from sales data
        if not customer_info:
            print(f"Customer {customer_name} not found in CRM, attempting to sync from sales data...")
            try:
                # Check if customer exists in sales data
                cursor.execute("""
                    SELECT DISTINCT buyer
                    FROM sales_product
                    WHERE buyer = %s AND notes LIKE '%INV%'
                """, (customer_name,))
                sales_customer = cursor.fetchone()
                
                if sales_customer:
                    print(f"Customer {customer_name} found in sales data, syncing to CRM...")
                    
                    # Get customer details from buyers table
                    cursor.execute("""
                        SELECT buyer, buyer_email, buyer_phone, buyer_address, primary_contact
                        FROM buyers
                        WHERE buyer = %s
                    """, (customer_name,))
                    buyer_data = cursor.fetchone()
                    
                    if buyer_data:
                        buyer, buyer_email, buyer_phone, buyer_address, primary_contact = buyer_data
                        
                        # Insert customer into crm_customers table
                        insert_data(table_name='crm_customers',
                                    audit_action='Auto-syncing Customer from Sales Data',
                                    customer=buyer,
                                    customer_email=buyer_email,
                                    customer_phone=buyer_phone,
                                    customer_address=buyer_address,
                                    primary_contact=primary_contact)
                        
                        print(f"✓ Auto-synced customer: {buyer}")
                        
                        # Update the customer with their invoice data
                        try:
                            # Get invoice data for this customer
                            cursor.execute("""
                                SELECT DISTINCT notes
                                FROM sales_product
                                WHERE buyer = %s AND notes LIKE '%%INV%%'
                                ORDER BY notes DESC
                            """, (customer_name,))
                            customer_invoices = cursor.fetchall()
                            
                            if customer_invoices:
                                # Clean invoice numbers and convert to JSON
                                cleaned_invoices = []
                                for invoice in customer_invoices:
                                    if invoice[0]:
                                        cleaned_number = str(invoice[0]).replace('{', '').replace('}', '').strip()
                                        cleaned_invoices.append(cleaned_number)
                                
                                if cleaned_invoices:
                                    import json
                                    invoices_json = json.dumps(cleaned_invoices)
                                    
                                    # Update the customer record with invoice data
                                    cursor.execute("""
                                        UPDATE crm_customers
                                        SET invoices = %s
                                        WHERE customer = %s
                                    """, (invoices_json, customer_name))
                                    
                                    print(f"✓ Updated invoices for auto-synced customer: {customer_name}")
                        except Exception as e:
                            print(f"⚠ Warning: Could not update invoices for {customer_name}: {e}")
                        
                        # Fetch the newly created customer info
                        cursor.execute("""
                            SELECT customer, customer_email, customer_phone,
                            customer_address, primary_contact, customer_status, customer_last_contact, customer_notes
                            FROM crm_customers WHERE customer = %s
                        """, (customer_name,))
                        customer_info = cursor.fetchall()
                        
                        print(f"Customer info now available: {len(customer_info)} records")
                    else:
                        print(f"⚠ Warning: Customer {customer_name} not found in buyers table")
                else:
                    print(f"⚠ Warning: Customer {customer_name} not found in sales data")
                    
            except Exception as e:
                print(f"❌ Error auto-syncing customer {customer_name}: {e}")
        
        if customer_info:
            print(f"Customer info fields: {len(customer_info[0]) if customer_info[0] else 0}")

        # Fetch follow-up tasks from crm_follow_ups table
        print(f"Fetching follow-up tasks for: {customer_name}")
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups WHERE customer = %s
        """, (customer_name,))
        follow_up_tasks = cursor.fetchall()
        
        print(f"Follow-up tasks found: {len(follow_up_tasks)} records")

        # Fetch call logs from crm_logs table
        print(f"Fetching call logs for: {customer_name}")
        cursor.execute("""
            SELECT id, customer, log_date, log_type, log_notes
            FROM crm_logs WHERE customer = %s
            ORDER BY log_date DESC, id DESC
        """, (customer_name,))
        call_logs = cursor.fetchall()
        
        print(f"Call logs found: {len(call_logs)} records")

        # Fetch customer invoice info
        print(f"Fetching invoice data for: {customer_name}")
        customer_invoice_data = get_customer_invoices(customer_name)
        
        print(f"Invoice data found: {len(customer_invoice_data) if customer_invoice_data else 0} records")

        # Calculate totals for the overview section
        total_bottles = 0
        total_revenue = 0.0
        product_breakdown = {}  # Dictionary to store product totals
        
        if customer_invoice_data and customer_invoice_data[1]:
            for invoice in customer_invoice_data[1]:
                if invoice[4]:  # bottles_sold
                    total_bottles += invoice[4]
                if invoice[5]:  # total_nzd
                    total_revenue += float(invoice[6])
                
                # Process product breakdown from product_details (index 3)
                if invoice[3]:  # product_details is a list of dictionaries
                    for product in invoice[3]:
                        product_name = product.get('name', 'Unknown Product')
                        quantity = product.get('quantity', 0)
                        
                        if product_name in product_breakdown:
                            product_breakdown[product_name] += quantity
                        else:
                            product_breakdown[product_name] = quantity
        
        print(f"Calculated totals - Bottles: {total_bottles}, Revenue: {total_revenue}")
        print(f"Product breakdown: {product_breakdown}")

        # Process contacts data
        customer_contacts = []
        if customer_info and customer_info[0] and customer_info[0][9]:  # contacts column (index 9)
            try:
                contacts_data = customer_info[0][9]
                if isinstance(contacts_data, str):
                    import json
                    contacts_data = json.loads(contacts_data)
                
                if isinstance(contacts_data, list):
                    customer_contacts = contacts_data
                print(f"Found {len(customer_contacts)} contacts for customer")
            except Exception as e:
                print(f"Error parsing contacts data: {e}")
                customer_contacts = []

        print("Rendering customer detail template...")
        return render_template('customer_detail.html', 
                            customer_info=customer_info, 
                            follow_up_tasks=follow_up_tasks, 
                            customer_invoice_data=customer_invoice_data,
                            call_logs=call_logs,
                            customer_name=customer_name,
                            total_bottles=total_bottles,
                            total_revenue=total_revenue,
                            product_breakdown=product_breakdown,
                            customer_contacts=customer_contacts,
                            invoice_button_enabled=INVOICE_BUTTON_ENABLED)
                            
    except Exception as e:
        print(f"❌ Error in crm_customer_page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('customer_detail.html', 
                            customer_info=None, 
                            follow_up_tasks=None, 
                            customer_invoice_data=None,
                            call_logs=None,
                            invoice_button_enabled=INVOICE_BUTTON_ENABLED,
                            total_bottles=0,
                            total_revenue=0.0,
                            product_breakdown={},
                            customer_contacts=[],
                            error_message=f"Error loading customer data: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/crm-sync-existing-customers', methods=['POST'])
def crm_sync_existing_customers():
    print("Accessed /crm-sync-existing-customers route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    try:
        print("Starting customer sync process...")
        
        # Fetch existing customers from crm_customers table
        cursor.execute("""
            SELECT DISTINCT(customer)
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
            ORDER BY customer
        """)
        crm_customers = cursor.fetchall()
        crm_customer_names = [customer[0] for customer in crm_customers]
        print(f"Found {len(crm_customer_names)} existing customers in CRM")

        # Fetch existing customers from sales_product table
        cursor.execute("""
            SELECT DISTINCT(buyer)
            FROM sales_product
            WHERE notes LIKE '%INV%'
            ORDER BY buyer
        """)
        existing_customers_from_sales = cursor.fetchall()
        print(f"Found {len(existing_customers_from_sales)} customers in sales data")

        # Compare existing customers from crm_customers and sales_product tables
        missing_customers = []
        for customer in existing_customers_from_sales:
            if customer[0] not in crm_customer_names:
                missing_customers.append(customer[0])

        print(f"Found {len(missing_customers)} customers to sync")

        # Fetch and insert missing customer data from buyers table
        synced_count = 0
        for customer_name in missing_customers:
            try:
                cursor.execute("""
                    SELECT buyer, buyer_email, buyer_phone, buyer_address, primary_contact
                    FROM buyers
                    WHERE buyer = %s
                """, (customer_name,))
                customer_data = cursor.fetchone()
                
                if customer_data:
                    buyer, buyer_email, buyer_phone, buyer_address, primary_contact = customer_data
                    
                    # Insert missing customer into crm_customers table
                    insert_data(table_name='crm_customers',
                                audit_action='Syncing Existing Customers into CRM',
                                customer=buyer,
                                customer_email=buyer_email,
                                customer_phone=buyer_phone,
                                customer_address=buyer_address,
                                primary_contact=primary_contact)
                    
                    print(f"✓ Synced customer: {buyer}")
                    synced_count += 1
                else:
                    print(f"⚠ Warning: No data found for customer {customer_name} in buyers table")
            except Exception as e:
                print(f"❌ Error syncing customer {customer_name}: {e}")
                continue
        
        print(f"Successfully synced {synced_count} out of {len(missing_customers)} customers")
        
        # Update existing customers with their invoice data
        print("Updating existing customers with invoice data...")
        update_existing_customers_with_invoices()
        
    except Exception as e:
        print(f"❌ Error in crm_sync_existing_customers: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def update_existing_customers_with_invoices():
    """Update existing customers in CRM with their invoice data"""
    print("Updating existing customers with invoice data...")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    try:
        # Get all customers from CRM
        cursor.execute("""
            SELECT DISTINCT customer
            FROM crm_customers
            WHERE customer IS NOT NULL AND customer != ''
        """)
        crm_customers = cursor.fetchall()
        
        updated_count = 0
        for customer_record in crm_customers:
            customer_name = customer_record[0]
            
            # Get invoice data for this customer
            cursor.execute("""
                SELECT DISTINCT notes
                FROM sales_product
                WHERE buyer = %s AND notes LIKE '%%INV%%'
            """, (customer_name,))
            customer_invoices = cursor.fetchall()
            
            if customer_invoices:
                # Clean invoice numbers and convert to JSON
                cleaned_invoices = []
                for invoice in customer_invoices:
                    if invoice[0]:
                        cleaned_number = str(invoice[0]).replace('{', '').replace('}', '').strip()
                        cleaned_invoices.append(cleaned_number)
                
                if cleaned_invoices:
                    import json
                    invoices_json = json.dumps(cleaned_invoices)
                    
                    # Update the customer record with invoice data
                    cursor.execute("""
                        UPDATE crm_customers
                        SET invoices = %s
                        WHERE customer = %s
                    """, (invoices_json, customer_name))
                    
                    updated_count += 1
                    print(f"✓ Updated invoices for customer: {customer_name}")
        
        connection.commit()
        print(f"Successfully updated {updated_count} customers with invoice data")
        
    except Exception as e:
        print(f"❌ Error updating customers with invoices: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def get_customer_invoices(customer_name):
    """Internal function to get customer invoice data"""
    print(f"Getting invoices for customer: {customer_name}")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    try:
        # Extract invoice data: Match buyer and invoices containing "INV"
        cursor.execute("""
            SELECT 
                buyer, 
                notes, 
                date, 
                jsonb_agg(
                    jsonb_build_object(
                        'name', p.key,
                        'quantity', (p.value->>'quantity')::int,
                        'unit_price', (p.value->>'unit_price')::numeric,
                        'total', (p.value->>'total_nzd')::numeric
                    )
                ) AS product_details,
                COALESCE(SUM((p.value->>'quantity')::int), 0) AS bottles_sold,
                COALESCE(SUM((p.value->>'total_nzd')::numeric), 0) AS total_nzd,
                invoice_total, 
                invoice_gst
            FROM sales_product,
                 jsonb_each(products->'products') AS p(key, value)
            WHERE buyer LIKE %s
            AND notes LIKE %s
            GROUP BY buyer, notes, date, invoice_total, invoice_gst
            ORDER BY notes DESC
        """, (f"%{customer_name}%", "%INV%"))

        customer_invoice_data = cursor.fetchall()

        # Extract invoices into a list and format as JSON
        cursor.execute("""
            SELECT DISTINCT(notes)
            FROM sales_product
            WHERE buyer LIKE %s
            AND notes LIKE %s
            ORDER BY notes DESC
        """, (f"%{customer_name}%", "%INV%"))
        customer_invoices = cursor.fetchall()

        # Clean invoice numbers - remove curly brackets and other special characters
        cleaned_invoices = []
        for invoice in customer_invoices:
            if invoice[0]:
                # Clean the invoice number by removing curly brackets and extra whitespace
                cleaned_number = str(invoice[0]).replace('{', '').replace('}', '').strip()
                cleaned_invoices.append((cleaned_number,))
        
        # Create new list and append customer_invoice_data to customer_invoices to return to the customer_detail.html template
        customer_invoice_info = []
        customer_invoice_info.append(cleaned_invoices)  # Use cleaned invoices
        customer_invoice_info.append(customer_invoice_data)
        
        # Convert to a simple list of invoice numbers for JSONB storage
        invoice_list = [invoice[0] for invoice in cleaned_invoices if invoice[0]]

        # Note: Invoice data is fetched for display only
        # The invoices field in crm_customers should be updated during customer sync, not here

        return customer_invoice_info
        
    except Exception as e:
        print(f"Error in get_customer_invoices: {e}")
        if connection:
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/crm-customer-invoices', methods=['POST'])
def crm_customer_invoices():
    """Route function to get customer invoices via HTTP request"""
    print("Accessed /crm-customer-invoices route")
    
    try:
        if request.is_json:
            data = request.get_json()
            customer_name = data.get("customer_name")
        else:
            customer_name = request.form.get("customer_name")
        
        if not customer_name:
            return jsonify({"error": "No customer name provided"}), 400
            
        customer_invoice_data = get_customer_invoices(customer_name)
        return jsonify({"invoices": customer_invoice_data})
        
    except Exception as e:
        print(f"Error in crm_customer_invoices route: {e}")
        return jsonify({"error": str(e)}), 500
    
@app.route('/crm-customer-invoice-data', methods=['POST'])
def crm_customer_invoice_data():
    print("Accessed /crm-customer-invoice-data route")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    
    try:
        
        if request.is_json:
            data = request.get_json()
            customer_name = data.get("customer_name")
        else:
            customer_name = request.form.get("customer_name")
        
        if not customer_name:
            return jsonify({"error": "No customer name provided"}), 400
            
        customer_invoice_data = get_customer_invoices(customer_name)
        return jsonify({"invoices": customer_invoice_data})
        
    except Exception as e:
        print(f"Error in crm_customer_invoice_data route: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/lal-audit', methods=['POST'])
def lal_audit():
    print("Accessed /lal-audit route")
    from lal_audit import ngs_audit_get_purchased
    from lal_audit import ngs_audit_get_flavor
    from lal_audit import ngs_audit_get_clearing
    from lal_audit import ngs_audit_get_vats
    from lal_audit import ngs_audit_bottles_sold
    from lal_audit import ngs_audit_get_purchased_remaining
    from lal_audit import ngs_audit_get_distillations_lal_not_in_vats
    from lal_audit import ngs_audit_get_distillations_not_in_vats
    from lal_audit import ngs_audit_get_lal_vats_not_bottled
    from lal_audit import ngs_audit_get_vats_not_bottled
    from lal_audit import ngs_audit_get_lal_bottles_not_sold
    from lal_audit import ngs_audit_get_bottles_stored
    from lal_audit import ngs_audit_get_customs_lodgements
    from lal_audit import ngs_audit_get_current_month_sold_bottles
    from lal_audit import ngs_audit_get_distillation_experiments
    from lal_audit import ngs_audit_get_flavor_experiments_flavor_codes
    from lal_audit import ngs_audit_get_flavor_experiments
    from lal_audit import ngs_audit_get_distillation_experiments_get_experiment_id
    from lal_audit import ngs_audit_populate_sales_product_table
    from lal_audit import ngs_audit_get_ex_stock_storage
    from lal_audit import ngs_audit_get_ex_stock_storage_ids
    from lal_audit import ngs_audit_populate_lal_purchased_table
    from lal_audit import ngs_audit_populate_lal_lodged_with_customs_table
    from lal_audit import ngs_audit_populate_lodgements_summary_table
    from lal_audit import ngs_audit_get_samples_consumed_table
    from lal_audit import ngs_audit_get_samples_consumed
    from lal_audit import ngs_audit_get_distillations_table
    from lal_audit import ngs_audit_get_mixing_vats_table
    from lal_audit import ngs_audit_get_bottling_table
    from lal_audit import ngs_audit_get_flavor_experiments_table
    from lal_audit import ngs_audit_get_distillation_experiments_table
    from lal_audit import ngs_audit_get_ex_stock_storage_table
    from lal_audit import ngs_audit_get_premix_lal
    from lal_audit import ngs_audit_get_premix_container_ids
    from lal_audit import ngs_audit_get_premix_table
    from lal_audit import ngs_audit_get_lal_flavor_experiments

    ngs_audit_get_purchased_data = ngs_audit_get_purchased()
    ngs_audit_get_flavor_data = ngs_audit_get_flavor()
    ngs_audit_get_clearing_data = ngs_audit_get_clearing()
    ngs_audit_get_vats_data = ngs_audit_get_vats()
    ngs_audit_bottles_sold_data = ngs_audit_bottles_sold()

    ngs_audit_get_purchased_remaining_data = ngs_audit_get_purchased_remaining()
    ngs_audit_get_flavor_lal_remaining_data = ngs_audit_get_distillations_lal_not_in_vats()
    ngs_audit_get_flavor_remaining_data = ngs_audit_get_distillations_not_in_vats()
    ngs_audit_get_vat_total_lal_remaining_data = ngs_audit_get_lal_vats_not_bottled(return_mode="total")
    ngs_audit_get_vat_breakdown_lal_remaining_data = ngs_audit_get_lal_vats_not_bottled(return_mode="breakdown")
    ngs_audit_get_vat_remaining_data = ngs_audit_get_vats_not_bottled()
    ngs_audit_get_lal_bottles_not_sold_data = ngs_audit_get_lal_bottles_not_sold()
    ngs_audit_get_bottles_stored_data = ngs_audit_get_bottles_stored()
    ngs_audit_get_customs_lodgements_data = ngs_audit_get_customs_lodgements()
    ngs_audit_get_current_month_sold_bottles_data = ngs_audit_get_current_month_sold_bottles()
    ngs_audit_get_distillation_experiments_data = ngs_audit_get_distillation_experiments()
    ngs_audit_get_flavor_experiments_flavor_codes_data = ngs_audit_get_flavor_experiments_flavor_codes()
    ngs_audit_get_flavor_experiments_data = ngs_audit_get_flavor_experiments()
    ngs_audit_get_distillation_experiments_get_experiment_id_data = ngs_audit_get_distillation_experiments_get_experiment_id()
    ngs_audit_get_ex_stock_storage_data = ngs_audit_get_ex_stock_storage()
    ngs_audit_get_ex_stock_storage_ids_data = ngs_audit_get_ex_stock_storage_ids()
    ngs_audit_populate_lal_purchased_table_data = ngs_audit_populate_lal_purchased_table()
    ngs_audit_populate_lal_lodged_with_customs_table_data = ngs_audit_populate_lal_lodged_with_customs_table()
    ngs_audit_populate_lodgements_summary_table_data = ngs_audit_populate_lodgements_summary_table()
    ngs_audit_get_samples_consumed_data = ngs_audit_get_samples_consumed()
    ngs_audit_get_samples_consumed_table_data = ngs_audit_get_samples_consumed_table()
    ngs_audit_get_distillations_table_data = ngs_audit_get_distillations_table()
    ngs_audit_get_mixing_vats_table_data = ngs_audit_get_mixing_vats_table()
    ngs_audit_get_bottling_table_data = ngs_audit_get_bottling_table()
    ngs_audit_get_flavor_experiments_table_data = ngs_audit_get_flavor_experiments_table()
    ngs_audit_get_distillation_experiments_table_data = ngs_audit_get_distillation_experiments_table()
    ngs_audit_get_ex_stock_storage_table_data = ngs_audit_get_ex_stock_storage_table()
    ngs_audit_get_premix_lal_data = ngs_audit_get_premix_lal()
    ngs_audit_get_premix_container_ids_data = ngs_audit_get_premix_container_ids()
    ngs_audit_get_premix_table_data = ngs_audit_get_premix_table()
    ngs_audit_get_lal_flavor_experiments_data = ngs_audit_get_lal_flavor_experiments()
    # Populate tables below summary for each section
    ngs_audit_populate_sales_product_table_data = ngs_audit_populate_sales_product_table()

    return render_template('lal_audit.html',
                         ngs_audit_get_purchased_data=ngs_audit_get_purchased_data,
                         ngs_audit_get_flavor_data=ngs_audit_get_flavor_data,
                         ngs_audit_get_clearing_data=ngs_audit_get_clearing_data,
                         ngs_audit_get_vats_data=ngs_audit_get_vats_data,
                         ngs_audit_bottles_sold_data=ngs_audit_bottles_sold_data,
                         ngs_audit_get_purchased_remaining_data=ngs_audit_get_purchased_remaining_data,
                         ngs_audit_get_flavor_lal_remaining_data=ngs_audit_get_flavor_lal_remaining_data,
                         ngs_audit_get_flavor_remaining_data=ngs_audit_get_flavor_remaining_data,
                         ngs_audit_get_vat_breakdown_lal_remaining_data=ngs_audit_get_vat_breakdown_lal_remaining_data,
                         ngs_audit_get_vat_remaining_data=ngs_audit_get_vat_remaining_data,
                         ngs_audit_get_lal_bottles_not_sold_data=ngs_audit_get_lal_bottles_not_sold_data,
                         ngs_audit_get_bottles_stored_data=ngs_audit_get_bottles_stored_data,
                         ngs_audit_get_customs_lodgements_data=ngs_audit_get_customs_lodgements_data,
                         ngs_audit_get_current_month_sold_bottles_data=ngs_audit_get_current_month_sold_bottles_data,
                         ngs_audit_get_distillation_experiments_data=ngs_audit_get_distillation_experiments_data,
                         ngs_audit_get_flavor_experiments_flavor_codes_data=ngs_audit_get_flavor_experiments_flavor_codes_data,
                         ngs_audit_get_flavor_experiments_data=ngs_audit_get_flavor_experiments_data,
                         ngs_audit_get_distillation_experiments_get_experiment_id_data=ngs_audit_get_distillation_experiments_get_experiment_id_data,
                         ngs_audit_populate_sales_product_table_data=ngs_audit_populate_sales_product_table_data,
                         ngs_audit_get_ex_stock_storage_data=ngs_audit_get_ex_stock_storage_data,
                         ngs_audit_get_ex_stock_storage_ids_data=ngs_audit_get_ex_stock_storage_ids_data,
                         ngs_audit_populate_lal_purchased_table_data=ngs_audit_populate_lal_purchased_table_data,
                         ngs_audit_populate_lal_lodged_with_customs_table_data=ngs_audit_populate_lal_lodged_with_customs_table_data,
                         ngs_audit_populate_lodgements_summary_table_data=ngs_audit_populate_lodgements_summary_table_data,
                         ngs_audit_get_samples_consumed_data=ngs_audit_get_samples_consumed_data,
                         ngs_audit_get_samples_consumed_table_data=ngs_audit_get_samples_consumed_table_data,
                         ngs_audit_get_distillations_table_data=ngs_audit_get_distillations_table_data,
                         ngs_audit_get_mixing_vats_table_data=ngs_audit_get_mixing_vats_table_data,
                         ngs_audit_get_bottling_table_data=ngs_audit_get_bottling_table_data,
                         ngs_audit_get_flavor_experiments_table_data=ngs_audit_get_flavor_experiments_table_data,
                         ngs_audit_get_distillation_experiments_table_data=ngs_audit_get_distillation_experiments_table_data,
                         ngs_audit_get_ex_stock_storage_table_data=ngs_audit_get_ex_stock_storage_table_data,
                         ngs_audit_get_premix_lal_data=ngs_audit_get_premix_lal_data,
                         ngs_audit_get_premix_container_ids_data=ngs_audit_get_premix_container_ids_data,
                         ngs_audit_get_premix_table_data=ngs_audit_get_premix_table_data,
                         ngs_audit_get_lal_flavor_experiments_data=ngs_audit_get_lal_flavor_experiments_data)

@app.route('/view-suppliers', methods=['POST'])
def view_suppliers():
    # Get data from the database
    print("Accessed /view-suppliers route")
    from data_fetch import view_suppliers
    
    data = view_suppliers()

    return render_template('view_suppliers.html', data=data)

@app.route('/view-expired-ingredients', methods=['POST'])
def view_expired_ingredients():
    print("Accessed /view-expired-ingredients route")
    from data_fetch import view_expired_ingredients

    data = view_expired_ingredients()

    return render_template('view_expired_ingredients.html', data=data)

@app.route('/email-upcoming-expired-ingredients', methods=['POST'])
def email_upcoming_expired_ingredients():
    print("Accessed /email-upcoming-expired-ingredients route")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    from data_fetch import view_upcoming_expired_ingredients

    data = view_upcoming_expired_ingredients()
    df = pd.DataFrame(data)
    df.columns = ['ID', 'Supplier', 'Ingredients', 'Quantity', 'WB Code', 'Expiry', 'Date Entered']
    html_table = df.to_html(index=False, header=True, classes='table table-striped')
    # Email settings
    app_password = 'bglgsnrkbxdynrsm'
    from initialize import email_settings, email_content
    sender_email, receiver_emails, email_subject = email_settings()
    email_content = email_content(html_table, sender_email, receiver_emails, email_subject)

    # Join the list of recipient emails into a single string
    receiver_emails_str = ', '.join(receiver_emails)

    # Connect to the SMTP server and send the email
    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()  # Use TLS
        server.login(sender_email, app_password)
        
        # Set the "To" header with the joined recipient emails string
        email_content.replace_header('To', receiver_emails_str)

        server.sendmail(sender_email, receiver_emails, email_content.as_string())

# Schedule the job to run view_upcoming_expired_ingredients every day at 8:00 AM
schedule.every().sunday.at("08:00").do(email_upcoming_expired_ingredients)

def send_due_tasks_email_scheduled():
    """Scheduled function to send due tasks email (runs outside Flask context)"""
    print("Running scheduled due tasks email...")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due today AND overdue
        today = date.today()
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND (follow_up_date <= %s OR follow_up_date IS NULL)
            ORDER BY 
                CASE 
                    WHEN follow_up_date IS NULL THEN 1
                    ELSE 0
                END,
                follow_up_date ASC,
                follow_up_priority ASC, 
                customer ASC
        """, (today,))
        due_tasks = cursor.fetchall()

        if not due_tasks:
            print("No tasks due or overdue today")
            return

        # Convert to DataFrame
        df = pd.DataFrame(due_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display and add overdue indicator
        def format_due_date(date_val):
            if date_val is None:
                return "No Date Set"
            date_obj = pd.to_datetime(date_val)
            if date_obj.date() < today:
                return f"{date_obj.strftime('%Y-%m-%d')} (OVERDUE)"
            elif date_obj.date() == today:
                return f"{date_obj.strftime('%Y-%m-%d')} (DUE TODAY)"
            else:
                return date_obj.strftime('%Y-%m-%d')
        
        df_display['Due Date'] = df_display['Due Date'].apply(format_due_date)
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count overdue vs due today
        overdue_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() < today)
        due_today_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() == today)
        no_date_count = sum(1 for task in due_tasks if task[2] is None)
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #FF6B6B; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .overdue {{ color: #dc3545; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h2>⚠️ Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(due_tasks)}</strong> follow-up task(s) requiring attention:</p>
            <ul>
                <li><strong style="color: #dc3545;">{overdue_count}</strong> overdue</li>
                <li><strong style="color: #ffc107;">{due_today_count}</strong> due today</li>
                <li><strong style="color: #6c757d;">{no_date_count}</strong> with no date set</li>
            </ul>
            {html_table}
            <p style="margin-top: 30px; text-align: center;">
                <a href="https://inventory.whistlebird.co.nz/crm" style="background-color: #4A90E2; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">View & Manage Tasks in CRM</a>
            </p>
            <p style="margin-top: 15px; color: #666; font-size: 14px;">
                This is an automated notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Due tasks email sent successfully for {len(due_tasks)} tasks")

    except Exception as e:
        print(f"Error sending due tasks email: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def send_weekly_tasks_email_scheduled():
    """Scheduled function to send weekly tasks email for next week (runs outside Flask context)"""
    print("Running scheduled weekly tasks email...")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date, timedelta

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due next week (Monday to Sunday)
        today = date.today()
        next_monday = today + timedelta(days=(7 - today.weekday()))
        next_sunday = next_monday + timedelta(days=6)
        
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND follow_up_date >= %s AND follow_up_date <= %s
            ORDER BY follow_up_date ASC, follow_up_priority ASC, customer ASC
        """, (next_monday, next_sunday))
        weekly_tasks = cursor.fetchall()

        if not weekly_tasks:
            print("No tasks due next week")
            return

        # Convert to DataFrame
        df = pd.DataFrame(weekly_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display
        df_display['Due Date'] = pd.to_datetime(df_display['Due Date']).dt.strftime('%Y-%m-%d (%A)')
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count tasks by day
        tasks_by_day = {}
        for task in weekly_tasks:
            task_date = pd.to_datetime(task[2]).strftime('%A, %B %d')
            if task_date not in tasks_by_day:
                tasks_by_day[task_date] = 0
            tasks_by_day[task_date] += 1
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #4A90E2; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .week-summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h2>📅 Follow-up Tasks for Next Week - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(weekly_tasks)}</strong> follow-up task(s) scheduled for next week.</p>
            
            <div class="week-summary">
                <h3>📊 Week Overview:</h3>
                <ul>
        """
        
        for day, count in sorted(tasks_by_day.items()):
            html_content += f'<li><strong>{day}:</strong> {count} task(s)</li>'
        
        html_content += f"""
                </ul>
            </div>
            
            {html_table}
            <p style="margin-top: 30px; color: #666; font-size: 14px;">
                This is an automated weekly notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Weekly Follow-up Tasks - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Weekly tasks email sent successfully for {len(weekly_tasks)} tasks")

    except Exception as e:
        print(f"Error sending weekly tasks email: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/email-due-tasks', methods=['POST'])
def email_due_tasks():
    print("Accessed /email-due-tasks route")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due today AND overdue (for testing)
        today = date.today()
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND (follow_up_date <= %s OR follow_up_date IS NULL)
            ORDER BY 
                CASE 
                    WHEN follow_up_date IS NULL THEN 1
                    ELSE 0
                END,
                follow_up_date ASC,
                follow_up_priority ASC, 
                customer ASC
        """, (today,))
        due_tasks = cursor.fetchall()

        if not due_tasks:
            print("No tasks due or overdue")
            return jsonify({"message": "No tasks due or overdue"}), 200

        # Convert to DataFrame
        df = pd.DataFrame(due_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display and add overdue indicator
        def format_due_date(date_val):
            if date_val is None:
                return "No Date Set"
            date_obj = pd.to_datetime(date_val)
            if date_obj.date() < today:
                return f"{date_obj.strftime('%Y-%m-%d')} (OVERDUE)"
            elif date_obj.date() == today:
                return f"{date_obj.strftime('%Y-%m-%d')} (DUE TODAY)"
            else:
                return date_obj.strftime('%Y-%m-%d')
        
        df_display['Due Date'] = df_display['Due Date'].apply(format_due_date)
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count overdue vs due today
        overdue_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() < today)
        due_today_count = sum(1 for task in due_tasks if task[2] and pd.to_datetime(task[2]).date() == today)
        no_date_count = sum(1 for task in due_tasks if task[2] is None)
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #FF6B6B; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .overdue {{ color: #dc3545; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h2>⚠️ Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(due_tasks)}</strong> follow-up task(s) requiring attention:</p>
            <ul>
                <li><strong style="color: #dc3545;">{overdue_count}</strong> overdue</li>
                <li><strong style="color: #ffc107;">{due_today_count}</strong> due today</li>
                <li><strong style="color: #6c757d;">{no_date_count}</strong> with no date set</li>
            </ul>
            {html_table}
            <p style="margin-top: 30px; text-align: center;">
                <a href="https://inventory.whistlebird.co.nz/crm" style="background-color: #4A90E2; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">View & Manage Tasks in CRM</a>
            </p>
            <p style="margin-top: 15px; color: #666; font-size: 14px;">
                This is an automated notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Follow-up Tasks Due & Overdue - {today.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Due tasks email sent successfully for {len(due_tasks)} tasks")
        return jsonify({"message": f"Email sent successfully for {len(due_tasks)} due/overdue tasks"}), 200

    except Exception as e:
        print(f"Error sending due tasks email: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route('/email-weekly-tasks', methods=['POST'])
def email_weekly_tasks():
    print("Accessed /email-weekly-tasks route")
    import smtplib
    import pandas as pd
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import datetime, date, timedelta

    from initialize import db_conn
    connection, cursor = db_conn()

    try:
        # Get follow-ups due next week (Monday to Sunday)
        today = date.today()
        next_monday = today + timedelta(days=(7 - today.weekday()))
        next_sunday = next_monday + timedelta(days=6)
        
        cursor.execute("""
            SELECT id, customer, follow_up_date, follow_up_priority, follow_up_status, follow_up_notes, follow_up_type
            FROM crm_follow_ups
            WHERE follow_up_status != 'completed'
            AND follow_up_date >= %s AND follow_up_date <= %s
            ORDER BY follow_up_date ASC, follow_up_priority ASC, customer ASC
        """, (next_monday, next_sunday))
        weekly_tasks = cursor.fetchall()

        if not weekly_tasks:
            print("No tasks due next week")
            return jsonify({"message": "No tasks due next week"}), 200

        # Convert to DataFrame
        df = pd.DataFrame(weekly_tasks)
        df.columns = ['ID', 'Customer', 'Due Date', 'Priority', 'Status', 'Notes', 'Type']
        
        # Remove ID column for display
        df_display = df.drop('ID', axis=1)
        
        # Format the due date for display
        df_display['Due Date'] = pd.to_datetime(df_display['Due Date']).dt.strftime('%Y-%m-%d (%A)')
        
        # Create HTML table
        html_table = df_display.to_html(index=False, header=True, classes='table table-striped', escape=False)
        
        # Count tasks by day
        tasks_by_day = {}
        for task in weekly_tasks:
            task_date = pd.to_datetime(task[2]).strftime('%A, %B %d')
            if task_date not in tasks_by_day:
                tasks_by_day[task_date] = 0
            tasks_by_day[task_date] += 1
        
        # Create email content
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #4A90E2; }}
                .table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                .table th, .table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                .table th {{ background-color: #f2f2f2; font-weight: bold; }}
                .table tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .priority-high {{ color: #dc3545; font-weight: bold; }}
                .priority-medium {{ color: #ffc107; font-weight: bold; }}
                .priority-low {{ color: #28a745; font-weight: bold; }}
                .week-summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h2>📅 Follow-up Tasks for Next Week - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}</h2>
            <p>You have <strong>{len(weekly_tasks)}</strong> follow-up task(s) scheduled for next week.</p>
            
            <div class="week-summary">
                <h3>📊 Week Overview:</h3>
                <ul>
        """
        
        for day, count in sorted(tasks_by_day.items()):
            html_content += f'<li><strong>{day}:</strong> {count} task(s)</li>'
        
        html_content += f"""
                </ul>
            </div>
            
            {html_table}
            <p style="margin-top: 30px; color: #666; font-size: 14px;">
                This is an automated weekly notification from your Whistlebird CRM system.
            </p>
        </body>
        </html>
        """

        # Email settings
        app_password = 'bglgsnrkbxdynrsm'
        sender_email = config.sender_email
        receiver_email = config.receiver_email
        
        # Create email
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Whistlebird CRM Notifications <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = f"Weekly Follow-up Tasks - {next_monday.strftime('%B %d')} to {next_sunday.strftime('%B %d, %Y')}"

        # Attach HTML content
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

        # Send email (authenticate as johnny@whistlebird.co.nz but send from sales@whistlebird.co.nz)
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('johnny@whistlebird.co.nz', app_password)
            server.send_message(msg)

        print(f"Weekly tasks email sent successfully for {len(weekly_tasks)} tasks")
        return jsonify({"message": f"Weekly email sent successfully for {len(weekly_tasks)} tasks"}), 200

    except Exception as e:
        print(f"Error sending weekly tasks email: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# Schedule the job to send due tasks email every day at 8:00 AM
schedule.every().day.at("14:30").do(send_due_tasks_email_scheduled)

# Schedule the job to send weekly tasks email every Sunday at 8:30 AM
schedule.every().sunday.at("08:30").do(send_weekly_tasks_email_scheduled)

def email_stock_sales():
    print("\n=== Starting email_stock_sales() function ===")
    from email.mime.image import MIMEImage
    import base64
    from email.mime.base import MIMEBase
    from email import encoders
    from initialize import create_email, send_email, send_emails_concurrently
    import datetime
    from database_insert import update_data
    connection, cursor = db_conn()

    try:
        # Step 1: Find buyers needing restock contact
        print("Finding buyers needing restock contact...")
        cursor.execute("""
            WITH buyer_stats AS (
                SELECT
                    buyer,
                    date,
                    bottles_sold,
                    MAX(date) OVER (PARTITION BY buyer) AS latest_date,
                    SUM(bottles_sold) OVER (PARTITION BY buyer) AS total_bottles_sold,
                    COUNT(CASE WHEN notes ILIKE '%Sample%' THEN 1 END) OVER (PARTITION BY buyer) AS sample_notes_count,
                    COUNT(notes) OVER (PARTITION BY buyer) AS total_notes_count,
                    FIRST_VALUE(bottles_sold) OVER (PARTITION BY buyer ORDER BY date DESC) as recent_bottles_sold,
                    FIRST_VALUE(unit_price) OVER (PARTITION BY buyer ORDER BY date DESC) as recent_unit_price
                FROM sales_product
                WHERE notes LIKE '%INV%'  -- Only consider invoice sales
            )
            SELECT DISTINCT b.buyer, b.buyer_email, b.primary_contact, b.buyer_phone, b.store_type,
                   bs.latest_date, bs.total_bottles_sold, bs.recent_bottles_sold, bs.recent_unit_price
            FROM buyers b
            JOIN (
                SELECT DISTINCT ON (buyer)
                    buyer, latest_date, total_bottles_sold, recent_bottles_sold, recent_unit_price,
                    sample_notes_count, total_notes_count
                FROM buyer_stats
                ORDER BY buyer, latest_date DESC
            ) bs ON b.buyer = bs.buyer
            WHERE (
                (bs.latest_date < CURRENT_DATE - INTERVAL '1 weeks' AND bs.total_bottles_sold < 2)
                OR
                (bs.latest_date < CURRENT_DATE - INTERVAL '2 weeks' AND bs.total_bottles_sold < 3)
                OR
                (bs.latest_date < CURRENT_DATE - INTERVAL '3 weeks' AND bs.total_bottles_sold < 4)
                OR
                bs.latest_date < CURRENT_DATE - INTERVAL '4 weeks'
            )
            AND b.buyer != 'WHISTLEBIRD INTERNAL (Personal)'
            AND (bs.sample_notes_count < bs.total_notes_count OR bs.sample_notes_count = 0)
            AND (b.restock_contact_date IS NULL OR b.restock_contact_date < CURRENT_DATE - INTERVAL '2 weeks')
            ORDER BY b.buyer;
        """)
        
        buyers_data = cursor.fetchall()
        
        if not buyers_data:
            print("No buyers found needing restock contact.")
            return

        print(f"Found {len(buyers_data)} buyers needing restock contact")

        # Load the Whistlebird logo
        try:
            with open('images/whistlebird_gold.png', 'rb') as f:
                image_data = f.read()
            print("✓ Loaded Whistlebird logo")
        except Exception as e:
            print(f"❌ Error loading logo: {str(e)}")
            image_data = None

        # Prepare notification emails
        prepared_emails = []
        for buyer_row in buyers_data:
            buyer, email, primary_contact, phone, store_type, latest_date, total_bottles, recent_bottles, recent_unit_price = buyer_row
            
            print(f"\n=== Processing buyer: {buyer} ===")
            print(f"Last purchase: {latest_date}")
            print(f"Total bottles: {total_bottles}")
            print(f"Most recent order: {recent_bottles} bottles")
            print(f"Most recent unit price: {recent_unit_price}")
            
            # Create notification email
            with open('email_templates/restock_email_notification.html', 'r') as html_file:
                notification_template = html_file.read()

            # Update contact date in database
            try:
                update_data(
                    table_name='buyers',
                    condition={'buyer': buyer},
                    restock_contact_date=datetime.date.today()
                )
                print(f"✓ Updated restock_contact_date for {buyer}")
            except Exception as e:
                print(f"❌ Error updating restock_contact_date: {str(e)}")

            # Prepare notification content
            notification_content = notification_template.replace('{buyer_buyer}', buyer)
            notification_content = notification_content.replace('{recipient}', email if email else 'No email')
            notification_content = notification_content.replace('{primary_contact}', primary_contact.split()[0] if primary_contact else 'there')
            notification_content = notification_content.replace('{primary_contact_full}', primary_contact if primary_contact else 'No contact')
            notification_content = notification_content.replace('{buyer_phone}', phone if phone else 'No phone')
            notification_content = notification_content.replace('{store_type}', store_type if store_type else 'Not specified')
            notification_content = notification_content.replace('{bottles_sold}', str(total_bottles))
            notification_content = notification_content.replace('{recent_bottles_sold}', str(recent_bottles))
            notification_content = notification_content.replace('{recent_unit_price}', str(recent_unit_price))
            notification_content = notification_content.replace('{date}', latest_date.strftime("%Y-%m-%d"))

            # Create email object
            notification_email = create_email(
                sender='sales@whistlebird.co.nz',
                recipients=['johnny@whistlebird.co.nz'],
                subject=f"Followup due now: {buyer}",
                email_content=notification_content,
                content_type='html',
                image_data=image_data,
                image_cid='whistlebird_gold'
            )
            prepared_emails.append(notification_email)
            print(f"✓ Prepared notification email for {buyer}")

        # Send all notification emails
        if prepared_emails:
            print(f"\nSending {len(prepared_emails)} notification emails...")
            send_emails_concurrently(prepared_emails)
            print("✓ All notification emails sent")
        else:
            print("No notification emails to send")

    except Exception as e:
        print(f"❌ Error in email_stock_sales: {str(e)}")
        raise
    finally:
        cursor.close()
        connection.close()
        print("\n=== Completed email_stock_sales() function ===")

# Schedule to run due follow ups for customers who need restock contact
# Disabled as we are replacing this functionality with the CRM - to re-enable this, uncomment the line below
#schedule.every().minute.do(email_stock_sales)

@app.route('/view-upcoming-expired-ingredients', methods=['POST'])
def view_upcoming_expired_ingredients():
    print("Accessed /view-upcoming-expired-ingredients route")

    from data_fetch import view_upcoming_expired_ingredients

    data = view_upcoming_expired_ingredients()

    return render_template('view_upcoming_expired_ingredients.html', data=data)

@app.route('/download-csv', methods=['POST'])
def download_csv():
    from initialize import db_conn
    import pandas as pd
    from flask import Flask, render_template, Response, send_file
    import io
    import zipfile
    connection, cursor = db_conn()

    # Get a list of all tables in the public schema
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        AND table_name NOT IN ('actions', 'audit')  -- Exclude specific tables if needed
    """)
    tables = cursor.fetchall()

    # Create a list to hold queries for each table
    queries = []

    # Generate a query for each table
    for table in tables:
        table_name = table[0]
        query = f"SELECT * FROM {table_name}"
        queries.append({"name": table_name, "query": query})

    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zipf:
        for query_info in queries:
            query_name = query_info["name"]
            query = query_info["query"]

            df = pd.read_sql_query(query, connection)
            csv_data = df.to_csv(index=False)

            # Add CSV data to the zip file
            zipf.writestr(f'{query_name}.csv', csv_data)

    # Create a Flask response with the zip file
    zip_buffer.seek(0)
    response = send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='data.zip'
    )
    connection.close()
    return response

@app.route('/add-purchase-entry', methods=['POST'])
def add_purchase_entry_route():
    print("Accessed /add-purchase-entry route")
    connection, cursor = db_conn()

    supplier = request.form.get("supplier") or request.form.get("new_supplier")
    litres_purchased = request.form.get("litres")

    if request.form.get("confirmation") == "true":
        insert_data(table_name='purchases_gns', audit_action='Purchase of GNS', supplier=supplier, gns_purchased_l=litres_purchased, abv=96.4)

    connection.close()

    return redirect(url_for('index'))

@app.route('/purchasing-gns', methods=['POST'])
def purchasing_gns():
    print("Accessed /purchasing-gns route")
    connection, cursor = db_conn()

    # Query the database for previous suppliers
    cursor.execute("SELECT DISTINCT supplier FROM suppliers WHERE supplier_type = 'gns' AND supplier IS NOT NULL AND supplier <> 'None';")
    previous_suppliers = [row[0] for row in cursor.fetchall()]

    # Combine rendering the template and redirecting to index
    print("Rendering template with previous suppliers:", previous_suppliers)
    return render_template('purchasing_gns.html', previous_suppliers=previous_suppliers)

@app.route('/delete-entry', methods=['POST', 'GET'])
def delete_entry():
    print("Accessed /delete-entry route")
    connection, cursor = db_conn()

    try:
        entry_id = request.form.get('deleteId')  # Get the ID to be deleted from the form

        # Delete the entry with the provided ID
        with connection, connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM actions WHERE id = %s", (entry_id,))
            connection.commit()

        return redirect(url_for('index'))  # Redirect back to the index page
    except Exception as e:
        print(e)  # Handle or log any errors that occur
        return redirect(url_for('index'))

@app.route('/top-buyers', methods=['POST'])
def top_buyers():
    print("Accessed /top-buyers-form route")
    from datetime import datetime, timedelta
    from initialize import db_conn
    connection, cursor = db_conn()

    # Get new buyers by month
    cursor.execute("""
        WITH first_purchases AS (
            SELECT 
                buyer,
                MIN(date) as first_purchase_date
            FROM sales_product
            WHERE notes LIKE '%INV%'
            GROUP BY buyer
        )
        SELECT 
            date_trunc('month', first_purchase_date) as month,
            COUNT(*) as count,
            STRING_AGG(buyer, ', ') as buyers
        FROM first_purchases
        GROUP BY date_trunc('month', first_purchase_date)
        ORDER BY month DESC;
    """)
    new_buyers_by_month = cursor.fetchall()

    # Get total unique buyers
    cursor.execute("""
        SELECT COUNT(DISTINCT buyer) 
        FROM sales_product 
        WHERE notes LIKE '%INV%';
    """)
    total_buyers = cursor.fetchone()[0]

    cursor.execute("""
        SELECT
            buyer,
            total_bottles_sold,
            percentage_of_total,
            ROUND(
                CASE
                    WHEN buyer = 'Total' THEN
                        (total_bottles_sold / NULLIF((CURRENT_DATE - (SELECT MIN(date) FROM sales_product)::DATE) / 7, 0))::numeric
                    ELSE
                        (total_bottles_sold / NULLIF((CURRENT_DATE - first_purchase_date::DATE) / 7, 0))::numeric
                END,
                2
            ) AS overall_rate_per_week,
            ROUND(
                CASE
                    WHEN buyer = 'Total' THEN
                        ((CURRENT_DATE - (SELECT MIN(date) FROM sales_product)::DATE) / 7)::numeric
                    ELSE
                        ((CURRENT_DATE - first_purchase_date::DATE) / 7)::numeric
                END
            ) AS total_weeks_since_first_order
        FROM (
                    SELECT
            buyer,
            -- Sum all bottles from all products JSONB for this buyer
            SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                FROM jsonb_each(products->'products'))) AS total_bottles_sold,
            -- Calculate percentage of total bottles
            (SUM((SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                 FROM jsonb_each(products->'products'))) * 100.0 / 
             (SELECT COALESCE(SUM((value->>'quantity')::int), 0)
              FROM sales_product sp, jsonb_each(sp.products->'products') AS p(key, value)
              WHERE sp.notes LIKE '%INV%')) AS percentage_of_total,
            MIN(date) AS first_purchase_date
        FROM sales_product
        WHERE notes LIKE '%INV%'
        AND products IS NOT NULL
        GROUP BY buyer

        UNION ALL

        SELECT
            'Total' AS buyer,
            -- Extract total bottles from all products JSONB
            (SELECT COALESCE(SUM((value->>'quantity')::int), 0)
             FROM sales_product sp, jsonb_each(sp.products->'products') AS p(key, value)
             WHERE sp.notes LIKE '%INV%') AS total_bottles_sold,
            NULL AS percentage_of_total,
            NULL AS first_purchase_date
        FROM sales_product
        ) AS combined_results
        GROUP BY buyer, total_bottles_sold, percentage_of_total, first_purchase_date
        ORDER BY
            CASE
                WHEN buyer = 'Total' THEN 0
                ELSE 1
            END,
            percentage_of_total DESC NULLS LAST;
    """)
    top_buyers = cursor.fetchall()

    # Setting month names dynamically
    current_month_name = datetime.now().strftime('%B %Y')  # Current month name
    last_month_name = (datetime.now() - timedelta(days=30)).strftime('%B %Y')  # Last month name
    two_months_ago_name = (datetime.now() - timedelta(days=60)).strftime('%B %Y')  # Two months ago name

    cursor.execute("""
        SELECT *
        FROM (
            SELECT 
                buyer,
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS current_month,
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '1 month' 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS last_month,
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '2 months' 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS two_months_ago
            FROM sales_product
            WHERE date >= date_trunc('month', CURRENT_DATE) - interval '2 months'
            AND products IS NOT NULL
            GROUP BY buyer

            UNION ALL

            SELECT
                'Total' AS buyer,
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS current_month,
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '1 month' 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS last_month,
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '2 months' 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0) AS two_months_ago
            FROM sales_product
            WHERE date >= date_trunc('month', CURRENT_DATE) - interval '2 months'
            AND products IS NOT NULL
        ) subquery
        ORDER BY 
            CASE WHEN buyer = 'Total' THEN 1 ELSE 0 END,  -- Ensures "Total" appears last
            buyer;
    """)
    three_month_totals = cursor.fetchall()

    cursor.execute("""
        SELECT
            buyer,
            ROUND(
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0)::numeric
                / EXTRACT(DAY FROM date_trunc('month', CURRENT_DATE + INTERVAL '1 month') - INTERVAL '1 day') * 7, 2
            ) AS current_month_weekly_rate,
            ROUND(
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '1 month' 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0)::numeric
                / EXTRACT(DAY FROM date_trunc('month', CURRENT_DATE) - INTERVAL '1 day') * 7, 2
            ) AS last_month_weekly_rate,
            ROUND(
                COALESCE(SUM(CASE WHEN date_trunc('month', date) = date_trunc('month', CURRENT_DATE) - interval '2 months' 
                    THEN (SELECT COALESCE(SUM((value->>'quantity')::int), 0) FROM jsonb_each(products->'products')) END), 0)::numeric
                / EXTRACT(DAY FROM date_trunc('month', CURRENT_DATE - INTERVAL '1 month') - INTERVAL '1 day') * 7, 2
            ) AS two_months_ago_weekly_rate
        FROM sales_product
        WHERE date >= date_trunc('month', CURRENT_DATE) - interval '2 months'
        AND products IS NOT NULL
        GROUP BY buyer
        ORDER BY buyer;
    """)
    weekly_rate_summary = cursor.fetchall()

    return render_template('top_buyers.html', 
                         top_buyers=top_buyers, 
                         three_month_totals=three_month_totals, 
                         current_month_name=current_month_name, 
                         last_month_name=last_month_name, 
                         two_months_ago_name=two_months_ago_name, 
                         weekly_rate_summary=weekly_rate_summary,
                         new_buyers_by_month=new_buyers_by_month,
                         total_buyers=total_buyers)

@app.route('/database-query-form', methods=['POST'])
def database_query_form():
    print("Accessed /database-query-form route")

    return render_template('database_query_form.html')

@app.route('/database-query', methods=['POST'])
def database_query():
    print("Accessed /database-query route")
    from initialize import db_conn_readonly
    import psycopg2
    import os
    import subprocess
    from psycopg2 import extensions
    connection, cursor = db_conn_readonly()

    sql_query = request.form['sql_query']
    print(sql_query)

    if sql_query.strip().startswith('\\'):
        # Set the PGPASSWORD environment variable
        os.environ['PGPASSWORD'] = 'wb_readonly'

        # Execute special command using psql command-line tool
        psql_command = f'psql -h host.docker.internal -p 5432 -U readonly_user -d whistlebird_inventory -c "{sql_query}"'
        query_results = subprocess.check_output(psql_command, shell=True, text=True)

        # Unset the PGPASSWORD environment variable after use
        del os.environ['PGPASSWORD']

        return render_template('database_query_result.html', query_results=query_results.splitlines())

    cursor.execute(sql_query)

    # Fetch column names
    columns = [desc[0] for desc in cursor.description]

    # Fetch rows
    rows = cursor.fetchall()
    return render_template('database_query_result.html', columns=columns, rows=rows)

@app.route('/add-product-form', methods=['POST'])
def add_product_form():
    print("Accessed /add-product-form route")

    return render_template('add_product.html')

@app.route('/add-product', methods=['POST'])
def add_product():
    print("Accessed /add-product route")
    connection, cursor = db_conn()

    product_name = request.form.get("productName")
    product_size = request.form.get("productSize")
    product_abv = request.form.get("productAbv")

    insert_data(table_name='products', audit_action='Add product to inventory', product_name=product_name, product_size=product_size, product_abv=product_abv)
    
    return render_template('index.html')

@app.route('/add-empty-bottles-form', methods=['GET'])
def add_empty_bottles_form():
    print("Accessed /add-empty-bottles-form route")
    connection, cursor = db_conn()

    # Query the database for previous suppliers
    cursor.execute("SELECT DISTINCT supplier FROM suppliers WHERE supplier_type = 'bottles' AND supplier IS NOT NULL AND supplier <> 'None';")
    previous_suppliers = [row[0] for row in cursor.fetchall()]

    return render_template('add_empty_bottles.html', previous_suppliers=previous_suppliers)

@app.route('/add-empty-bottles', methods=['POST'])
def add_empty_bottles():
    print("Accessed /add-empty-bottles route")
    connection, cursor = db_conn()

    # Query the database for previous suppliers
    cursor.execute("SELECT DISTINCT supplier FROM suppliers WHERE supplier_type = 'bottles' AND supplier IS NOT NULL AND supplier <> 'None';")
    previous_suppliers = [row[0] for row in cursor.fetchall()]

    # Get the form data
    empty_bottles_count = request.form.get("emptyBottlesCount")
    supplier = request.form.get("supplier") or request.form.get("new_supplier")

    # Insert the data into the database
    insert_data(table_name='purchases_empty_bottles', audit_action='Add empty bottles to inventory', supplier=supplier, bottle_size_ml=700, empty_bottles_stored=empty_bottles_count)
    
    connection.close()

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/add-flavor-form', methods=['POST'])
def add_flavor_form():
    print("Accessed /add-flavor-form route")
    connection, cursor = db_conn()

    cursor.execute("SELECT DISTINCT flavor_code FROM product_actions_flavors WHERE flavor_code IS NOT NULL AND flavor_code <> 'None';")
    previous_flavor_codes = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT ingredients, ingredients_code FROM purchases_ingredients ORDER BY id desc;")
    ingredient_data = cursor.fetchall()
    available_ingredients = []
    for row in ingredient_data:
        available_ingredients.append({
            'ingredient_name': row[0],
            'ingredient_code': row[1]
        })

    cursor.execute("SELECT DISTINCT flavor_batch from product_actions_flavors WHERE flavor_batch IS NOT NULL AND flavor_batch <> 'None';")
    previous_flavor_batch_codes = [row[0] for row in cursor.fetchall()]

    connection.close()

    # Define flavor ingredients
    recipes = {
      'WB25 (Wildflower)': [
          'juniper berries (himalayan)', 'juniper berries (macedonia)', 'orris root', 'coriander seeds', 'whole nutmeg (organic)', 'lemon juice', 'orange peel - dried', 'hibiscus flowers', 'liquorice root', 'grapefruit juice', 'green tea', 'cardamom pods', 'lemon peel', 'persian black lime', 'sumac berries - ground', 'lemon myrtle', 'dried mango slices', 'dried apple ring', 'elderflower'
      ],
      'WB30 (Rosella)': [
        'juniper berries (himalayan)', 'juniper berries (macedonia)', 'kawakawa leaf', 'whole nutmeg (organic)', 'orange peel (fresh)', 'orange juice (fresh)', 'cinnamon', 'liquorice root', 'szechaun pepper'
      ]
    }

    return render_template('add_flavor.html', previous_flavor_codes=previous_flavor_codes, previous_flavor_batch_codes=previous_flavor_batch_codes, available_ingredients=available_ingredients, recipes=recipes)

@app.route('/add-flavor', methods=['POST'])
def add_flavor():
    print("Accessed /add-flavor route")

    # Get the form data
    flavor_stored = request.form.get("flavorStored")
    clearing_amount = request.form.get("clearingAmount")
    clearing_abv = request.form.get("clearingAbv")
    flavor_code = request.form.get("flavorCode")
    flavor_batch_code = request.form.get("flavorBatchCode")

    ingredient_codes = request.form.getlist('ingredientCodeSelection[]')
    print(ingredient_codes)

    # insert into database
    insert_data(table_name='product_actions_flavors', audit_action='Add flavor to inventory', flavor_stored_ml=flavor_stored, clearing_amount=clearing_amount, clearing_abv=clearing_abv, flavor_code=flavor_code, flavor_batch=flavor_batch_code, ingredient_codes=ingredient_codes)

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/add-premix-form', methods=['POST'])
def add_premix_form():
    print("Accessed /add-premix-form route")

    return render_template('add_premix.html')

@app.route('/add-premix', methods=['POST'])
def add_premix():
    print("Accessed /add-premix roiye")

    # Fetch data from form input
    notes = request.form.get("notes")
    container_id = request.form.get("containerId")
    if container_id:
        container_id = container_id.strip("(),'")  # Remove parentheses, commas and quotes
    
    try:
        alcohol_volume = float(request.form.get("alcoholVolume", 0))  # Default to 0 if missing
        alcohol_abv = float(request.form.get("alcoholAbv", 0))  # Default to 0 if missing

        lal = alcohol_volume * (alcohol_abv / 100)

    except ValueError:
        return "Invalid input: Please enter numeric values.", 400  # Return HTTP 400 Bad Request

    # Store results in DB
    insert_data(table_name='product_actions_create_premix', audit_action='Creating premix solution for product actions', notes=notes, alcohol_volume=alcohol_volume, alcohol_abv=alcohol_abv, lal=lal, container_id=container_id)

    print(f"LAL for /add-premix = {lal}")
    return render_template('index.html')

@app.route('/add-ex-stock-storage-form', methods=['POST'])
def add_ex_stock_storage_form():
    print("Accessed /add-ex-stock-storage-form route")

    return render_template('add_ex_stock_storage.html')

@app.route('/add-ex-stock-storage', methods=['POST'])
def add_ex_stock_storage():
    print("Accessed /add-ex-stock-storage route")

    # Fetch data from form input
    notes = request.form.get("notes")
    
    try:
        if request.form.get("productName") == "Wildflower":
            abv = float(44)
            bottles_stored = float(request.form.get("bottlesStored", 0))
            product_name = request.form.get("productName")
            storage_id = request.form.get("storageID")
            bottle_size_ml = float(700)
        elif request.form.get("productName") == "Rosella":
            abv = float(40)
            bottles_stored = float(request.form.get("bottlesStored", 0))
            product_name = request.form.get("productName")
            storage_id = request.form.get("storageID")
            bottle_size_ml = float(700)

        lal = (bottles_stored * 0.7 * abv) / 100
        
    except ValueError:
        return "Invalid input: Please enter numeric values.", 400  # Return HTTP 400 Bad Request

    # Store results in DB
    insert_data(table_name='product_actions_ex_stock_storage', audit_action='Recording ex-stock storage', notes=notes, product_name=product_name, storage_id=storage_id, bottle_size_ml=bottle_size_ml, abv=abv, bottles_stored=bottles_stored, lal=lal)

    print(f"LAL for /add-ex-stock-storage = {lal}")
    return render_template('index.html')

@app.route('/add-distillation-experiment-form', methods=['POST'])
def add_distillation_experiment_form():
    print("Accessed /add-distillation-experiment-form route")

    connection, cursor = db_conn()

    # Fetch flavor experiments from database
    cursor.execute("SELECT flavor_code FROM product_actions_flavor_experiments WHERE flavor_code IS NOT NULL AND flavor_code <> 'None';")
    previous_flavor_codes = [row[0] for row in cursor.fetchall()]

    return render_template('distillation_experiment.html', previous_flavor_codes=previous_flavor_codes)

@app.route('/add-distillation-experiment', methods=['POST'])
def add_distillation_experiment():
    print("Accessed /add-distillation-experiment route")
    
    # Fetch data from form input
    alcohol_amount = request.form.get("alcoholAmount")
    abv = request.form.get("alcoholAbv")
    flavor_codes = request.form.getlist("flavorCode[]")
    bottles_used = request.form.get("bottlesUsed")
    bottle_abv = request.form.get("bottleAbv")
    notes = request.form.get("experimentSummary")
    experiment_id = request.form.get("experimentId")

    # Handle both bottles used and alcohol amount
    if bottles_used and alcohol_amount:
        bottle_abv = float(bottle_abv)
        bottles_lal = round(float(bottles_used) * 0.7 * float(bottle_abv / 100), 3)
        alcohol_used_l = round(float(alcohol_amount), 3)
        abv = float(abv)
        alcohol_used_lal = round(float(alcohol_amount) * (abv / 100), 3)
        lal = round(float(alcohol_used_lal) + float(bottles_lal), 3)
    
    # Handle empty alcohol_amount
    if not alcohol_amount or alcohol_amount == "":
        bottles_used = float(bottles_used) if bottles_used else 0
        bottle_abv = float(bottle_abv)
        abv = 0
        alcohol_used_l = round(float(bottles_used) * 0.7, 3)
        lal = round(float(alcohol_used_l) * float(bottle_abv / 100), 3)

    if not bottles_used or bottles_used == "":
        bottles_used = 0
        bottle_abv = 0
        abv = float(abv)
        alcohol_used_l = round(float(alcohol_amount), 3)
        lal = round(float(alcohol_used_l) * (abv / 100), 3)

    # Set ABV to 93% due to known ABV from T500
    alcohol_yield_abv = float(93)

    # Determine yield based on 93% and total volume distilled
    alcohol_yield_l = round(lal / (alcohol_yield_abv / 100), 3)

    # Insert into database
    insert_data(table_name='product_actions_distillation_experiments', 
                audit_action='Performed distillation experiment using existing product', 
                alcohol_used_l=alcohol_used_l, 
                bottles_used=bottles_used,
                bottle_abv=bottle_abv,
                abv=abv, 
                alcohol_yield_l=alcohol_yield_l, 
                alcohol_yield_abv=alcohol_yield_abv, 
                notes=notes, 
                flavor_codes=flavor_codes,
                lal=lal,
                experiment_id=experiment_id)
    
    return render_template('index.html')

@app.route('/flavor-experiment-form', methods=['POST'])
def flavor_experiment_form():
    print("Accessed /flavor-experiment-form route")
    connection, cursor = db_conn()

    cursor.execute("SELECT DISTINCT flavor_code FROM product_actions_flavor_experiments WHERE flavor_code IS NOT NULL AND flavor_code <> 'None';")
    previous_flavor_codes = [row[0] for row in cursor.fetchall()]
    
    return render_template('flavor_experiment.html', previous_flavor_codes=previous_flavor_codes)

@app.route('/flavor-experiment', methods=['POST'])
def flavor_experiment():
    print("Accessed /flavor-experiment route")

    # Get the form data
    flavor_stored = request.form.get("flavorStored")
    clearing_amount = request.form.get("clearingAmount")
    clearing_abv = request.form.get("clearingAbv")
    flavor_code = request.form.get("flavorCode")

    # Insert data into database
    insert_data(table_name='product_actions_flavor_experiments', audit_action='Flavor experiment', flavor_stored_ml=flavor_stored, clearing_amount=clearing_amount, clearing_abv=clearing_abv, flavor_code=flavor_code)

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/sample-experiment-form', methods=['POST'])
def sample_experiment_form():
    print("Accessed /sample-experiment-form route")

    connection, cursor = db_conn()

    cursor.execute("SELECT DISTINCT flavor_code FROM product_actions_flavor_experiments WHERE flavor_code IS NOT NULL AND flavor_code <> 'None';")
    previous_flavor_codes = [row[0] for row in cursor.fetchall()]

    return render_template('sample_experiment.html', previous_flavor_codes=previous_flavor_codes)

@app.route('/sample-experiment', methods=['POST'])
def sample_experiment():
    print("Accessed /sample-experiment route")

    # Get the form data
    flavor_code = request.form.get("flavorCode")
    abv = float(request.form.get("abv", 0))  # Convert to float, default to 0 if None
    bottle_size_ml = float(request.form.get("bottle_size_ml", 0))  # Convert to float, default to 0 if None
    number_of_bottles = float(request.form.get("number_of_bottles", 0))  # Convert to float, default to 0 if None
    notes = request.form.get("notes")

    lal = round(number_of_bottles * (bottle_size_ml / 1000) * (abv / 100), 3)

    # Insert data into database
    insert_data(table_name='product_actions_samples_consumed', audit_action='Sample used - noting for customs lodgement', flavor_code=flavor_code, abv=abv, bottle_size_ml=bottle_size_ml, number_of_bottles=number_of_bottles, lal=lal, notes=notes)

    return render_template('index.html')

@app.route('/create-sample-form', methods=['POST'])
def create_sample_form():
    print("Accessed /create-sample-form route")

    connection, cursor = db_conn()

    cursor.execute("SELECT DISTINCT flavor_code FROM product_actions_flavors WHERE flavor_code IS NOT NULL AND flavor_code <> 'None';")
    previous_flavor_codes = [row[0] for row in cursor.fetchall()]

    return render_template('create_sample.html', previous_flavor_codes=previous_flavor_codes)

@app.route('/create-sample', methods=['POST'])
def create_sample():
    print("Accessed /create-sample route")

    # Get the form data
    number_of_bottles = float(request.form.get("number_of_bottles"))
    abv = float(request.form.get("abv"))
    bottle_size_ml = float(request.form.get("bottle_size_ml"))
    flavor_code = request.form.get("flavorCode")
    notes = request.form.get("notes")

    lal = number_of_bottles * (bottle_size_ml / 1000) * (abv / 100)

    # Insert data into database
    insert_data(table_name='product_actions_samples_created', audit_action='Create sample', number_of_bottles=number_of_bottles, abv=abv, bottle_size_ml=bottle_size_ml, flavor_code=flavor_code, notes=notes, lal=lal)

    return render_template('index.html')

@app.route('/bottled-product-form', methods=['POST'])
def bottled_production_form():
    print("Accessed /bottled-production-form route")

    connection, cursor = db_conn()

    cursor.execute("""
    SELECT DISTINCT bottle_size_ml
        FROM product_actions_bottling
        WHERE bottle_size_ml IS NOT NULL AND bottle_size_ml <> 0;
    """)
    previous_sizes = [row[0] for row in cursor.fetchall()]

    cursor.execute("""
    SELECT DISTINCT abv
        FROM product_actions_bottling
        WHERE abv IS NOT NULL AND abv <> 0;
    """)
    previous_abv = [row[0] for row in cursor.fetchall()]

    cursor.execute("""
    SELECT DISTINCT vat_batch
        FROM product_actions_flavor_vat
        WHERE vat_batch IS NOT NULL AND vat_batch <> '';
    """)
    vat_batches = [row[0] for row in cursor.fetchall()]

    return render_template('bottled_product.html', previous_sizes=previous_sizes, previous_abv=previous_abv, vat_batches=vat_batches)

@app.route('/bottled-product', methods=['POST'])
def bottled_product():
    print("Accessed /bottled-product route")

    bottles_stored = request.form.get("bottlesStored")
    abv = request.form.get("abv")
    bottle_size_ml = request.form.get("bottle_size_ml")
    vat_batch = request.form.get("vatBatches")
    bottle_batch = request.form.get("bottleBatch")

    # Insert data into database
    insert_data(table_name='product_actions_bottling', audit_action='Add bottled product to inventory', bottles_stored=bottles_stored, abv=abv, bottle_size_ml=bottle_size_ml, vat_batch=vat_batch, bottle_batch=bottle_batch)

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/add-flavor-to-vat-form', methods=['POST'])
def add_flavor_to_vat_form():
    print("Accessed /add-flavor-to-vat-form route")
    
    connection, cursor = db_conn()

    cursor.execute("""
    SELECT DISTINCT abv
        FROM product_actions_flavor_vat
        WHERE abv IS NOT NULL AND abv <> 0;
    """)
    previous_abv = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT flavor_batch FROM product_actions_flavors WHERE flavor_batch IS NOT NULL AND flavor_batch <> 'None';")
    flavor_batches = [row[0] for row in cursor.fetchall()]

    cursor.execute("""
    SELECT DISTINCT vat_batch
        FROM product_actions_flavor_vat
        WHERE vat_batch IS NOT NULL AND vat_batch <> '';
    """)
    vat_batches = [row[0] for row in cursor.fetchall()]

    return render_template('add_flavor_to_vat.html', previous_abv=previous_abv, flavor_batches=flavor_batches, vat_batches=vat_batches)

@app.route('/add-flavor-to-vat', methods=['POST'])
def add_flavor_to_vat():
    print("Accessed /add-flavor-to-vat route")

    # fetch values from form above
    abv = request.form.get("abv")
    volume_stored = request.form.get("volumeStored")
    flavor_batches = request.form.getlist("flavorBatches[]")
    vat_batch = request.form.get("vatBatch")

    # Insert data into database
    insert_data(table_name='product_actions_flavor_vat', audit_action='Add flavor to vat', abv=abv, volume_amount=volume_stored, vat_batch=vat_batch, flavor_batch=flavor_batches)

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/add-alcohol-form', methods=['POST'])
def add_alcohol_form():
    print("Accessed /add-alcohol-form route")

    connection, cursor = db_conn()

    # Fetch existing ABV options
    cursor.execute("SELECT DISTINCT abv FROM product_actions_ethanol")
    previous_abv = [row[0] for row in cursor.fetchall()]

    return render_template('add_alcohol.html', previous_abv=previous_abv)

@app.route('/add-alcohol', methods=['POST'])
def add_alcohol():
    print("Accessed /add-alcohol route")

    # Fetch form values
    abv = request.form.get("abv")
    alcohol_stored_l = request.form.get("alcohol_stored_l")
    notes = request.form.get("notes")

    print(abv)
    print(alcohol_stored_l)
    print(notes)

    # Insert data into database
    insert_data(table_name='product_actions_ethanol', audit_action='Stored or diluted alcohol', abv=abv, alcohol_stored_l=alcohol_stored_l, notes=notes)

    return render_template('index.html')

@app.route('/bottle-sales-form', methods=['POST'])
def bottle_sales_form():
    print("Accessed /bottle-sales-form route")
    connection, cursor = db_conn()

    cursor.execute("SELECT DISTINCT buyer FROM buyers WHERE buyer is NOT NULL AND buyer <> 'None';")
    previous_buyers = [row[0] for row in cursor.fetchall()]

    cursor.execute("""
    SELECT DISTINCT abv
        FROM product_actions_bottling
        WHERE abv IS NOT NULL AND abv <> 0;
    """)
    previous_abv = [row[0] for row in cursor.fetchall()]

    cursor.execute("""
    SELECT DISTINCT bottle_size_ml
        FROM product_actions_bottling
        WHERE bottle_size_ml IS NOT NULL AND bottle_size_ml <> 0;
    """)
    previous_sizes = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT bottle_batch FROM product_actions_bottling WHERE (bottle_batch IS NOT NULL OR bottle_batch <> 'None');")
    bottle_batches = [row[0] for row in cursor.fetchall()]

    return render_template('bottle_sales.html', previous_buyers=previous_buyers, previous_abv=previous_abv, previous_sizes=previous_sizes, bottle_batches=bottle_batches)

@app.route('/bottle-sales', methods=['POST'])
def bottle_sales():
    print("Accessed /bottle-sales route")
    from decimal import Decimal, ROUND_HALF_UP
    from math import ceil

    # Get the form data
    buyer = request.form.get("previousBuyers")
    number_of_bottles = request.form.get("numberOfBottles")
    abv = request.form.get("abv")
    bottle_size_ml = request.form.get("bottle_size_ml")
    bottle_batches = request.form.getlist("bottleBatches")
    notes = request.form.getlist("notes")

    # Convert variables to numeric types
    number_of_bottles = int(number_of_bottles)
    bottle_size_ml = float(bottle_size_ml)
    abv = float(abv)

    # Calculate lal & duty owed from sale
    duty_price = 67.22
    total_alcohol_ml = number_of_bottles * bottle_size_ml * abv
    lal = total_alcohol_ml / 100000  # Convert mL to L
    duty_amount = lal * duty_price

    # Use the Decimal class for precise arithmetic and rounding
    rounded_duty_amount = Decimal(duty_amount).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
    tenths = (rounded_duty_amount * 100) % 10
    if tenths >= 5:
        rounded_duty_amount = rounded_duty_amount + Decimal('0.01')

    # Insert data into database
    insert_data(table_name='sales_product', audit_action='Bottle sales', buyer=buyer, bottles_sold=number_of_bottles, abv=abv, bottle_size_ml=bottle_size_ml, lal=lal, duty_amount=rounded_duty_amount, bottle_batch=bottle_batches, notes=notes)

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/add-sales-product-samples-form', methods=['POST'])
def add_sales_product_samples_form():
    print("Accessed /add-sales-product-samples-form route")

    connection, cursor = db_conn()

    cursor.execute("SELECT DISTINCT buyer FROM buyers WHERE buyer is NOT NULL AND buyer <> 'None' ORDER BY buyer;")
    buyers = [row[0] for row in cursor.fetchall()]

    return render_template('add_sales_product_samples.html', buyers=buyers)

@app.route('/add-sales-product-samples', methods=['POST'])
def add_sales_product_samples():
    print("Accessed /add-sales-product-samples route") 

    # Get the form data
    date = request.form.get("date")
    action = request.form.get("action")
    buyer = request.form.get("buyer")
    samples_provided = float(request.form.get("samplesProvided"))
    product = request.form.get("product")
    abv = float(request.form.get("abv"))
    bottle_size_ml = float(request.form.get("bottleSizeMl"))

    lal = samples_provided * (bottle_size_ml / 1000) * (abv / 100)

    # Insert data into database
    insert_data(table_name='sales_product_samples', audit_action='Add sales product samples', date=date, action=action, buyer=buyer, samples_provided=samples_provided, product=product, abv=abv, bottle_size_ml=bottle_size_ml, lal=lal)

    # Redirect back to the index page
    return render_template('index.html')   

@app.route('/add-botanicals-to-inventory-form', methods=["POST"])
def add_botanicals_to_inventory_form():
    print("Accessed /add-botanicals-to-iventory-form route")

    connection, cursor = db_conn()

    # Retrieve ingredients from DB
    cursor.execute("SELECT DISTINCT ingredients FROM purchases_ingredients WHERE ingredients is NOT NULL AND ingredients <> 'None';")
    previous_ingredients = [row[0] for row in cursor.fetchall()]

    # Retrieve suppliers from DB
    cursor.execute("SELECT DISTINCT supplier FROM suppliers WHERE supplier_type = 'botanicals/ingredients' AND supplier is NOT NULL AND supplier <> 'None';")
    previous_suppliers = [row[0] for row in cursor.fetchall()]

    return render_template('add_botanicals_to_inventory.html', previous_ingredients=previous_ingredients, previous_suppliers=previous_suppliers)

@app.route('/get-ingredient-codes', methods=['POST'])
def get_ingredient_codes():
    print("Accessed /get-ingredient-codes route")
    from flask import jsonify
    connection, cursor = db_conn()

    selected_ingredient = request.form.get('selected_ingredient')
    # Query the database to retrieve previous ingredient codes based on selected_ingredient
    # Return the results as JSON
    cursor.execute("SELECT DISTINCT ingredients_code FROM purchases_ingredients WHERE ingredients = %s;", (selected_ingredient,))
    ingredient_codes = [row[0] for row in cursor.fetchall()]

    # Close the cursor and connection
    cursor.close()
    connection.close()

    return jsonify({'ingredient_codes': ingredient_codes})

@app.route('/add-botanicals-to-inventory', methods=["POST"])
def add_botanicals_to_inventory():
    print("Accessed /add-botanicals-to-inventory route")
    connection, cursor = db_conn()

    # Get the form data
    supplier = request.form.get("supplier")
    ingredients = request.form.get("ingredients")
    ingredients_amount = request.form.get("ingredients_amount")
    ingredients_expiry = request.form.get('ingredients_expiry')
    ingredient_code = request.form.get("ingredients_code")

    if ingredient_code == "new_ingredient_code":
        ingredient_code = request.form.get("new_ingredient_code")

    # Call your function to store the data in the database
    insert_data(table_name='purchases_ingredients', audit_action='Adding botanicals to inventory', supplier=supplier, ingredients=ingredients, ingredients_amount=ingredients_amount, ingredients_expiry=ingredients_expiry, ingredients_code=ingredient_code)

    return render_template('index.html')

@app.route('/add-supplier-form', methods=['POST', 'GET'])
def add_supplier_form():
    print("Accessed /add-supplier-form")

    connection, cursor = db_conn()

    # Retrieve suppliers from DB
    cursor.execute("SELECT DISTINCT supplier FROM suppliers WHERE supplier is NOT NULL AND supplier <> 'None';")
    previous_suppliers = [row[0] for row in cursor.fetchall()]

    supplier_type = ["gns", "botanicals/ingredients", "bottles"]

    return render_template('add_supplier.html', previous_suppliers=previous_suppliers, supplier_type=supplier_type)

@app.route('/add-supplier', methods=["POST"])
def add_supplier():
    print("Accessed /add-supplier route")

    connection, cursor = db_conn()

    # Get the form data
    supplier = request.form.get("supplier") or request.form.get("new_supplier")
    supplier_contact = request.form.get("supplierContact", '')
    supplier_location = request.form.get("supplierLocation", '')
    supplier_number = request.form.get("supplierNumber", '')
    supplier_type = request.form.get("supplierType")
    
    insert_data(table_name='suppliers', audit_action='Add supplier to suppliers table', supplier=supplier, supplier_contact=supplier_contact, supplier_location=supplier_location, supplier_number=supplier_number, supplier_type=supplier_type)

    connection.close()

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/add-buyer-form', methods=['POST', 'GET'])
def add_buyer_form():
    print("Accessed /add-buyer-form route")

    connection, cursor = db_conn()

    # Retrieve buyers from the DB
    cursor.execute("SELECT DISTINCT buyer FROM buyers WHERE buyer is NOT NULL AND buyer <> 'None';")
    previous_buyers = [row[0] for row in cursor.fetchall()]

    return render_template('add_buyer.html', previous_buyers=previous_buyers)

@app.route('/add-buyer', methods=["POST"])
def add_buyer():
    print("Accessed /add-buyer route")

    connection, cursor = db_conn()

    # Get the form data
    buyer = request.form.get("buyer") or request.form.get("new_buyer")
    primary_contact = request.form.get("primaryContact")
    buyer_address = request.form.get("buyerAddress")
    buyer_phone = request.form.get("buyerPhone")
    buyer_email = request.form.get("buyerEmail")
    
    insert_data(table_name='buyers', audit_action='Add buyer to buyers table', buyer=buyer, primary_contact=primary_contact, buyer_address=buyer_address, buyer_phone=buyer_phone, buyer_email=buyer_email)

    connection.close()

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/ingredient-tracer-form', methods=["POST"])
def ingredient_tracer_form():
    print("Accessed /ingredient-tracer-form route")

    connection, cursor = db_conn()

    # SQL
    cursor.execute("SELECT DISTINCT ingredients FROM purchases_ingredients;")
    ingredients = [row[0] for row in cursor.fetchall()]

    return render_template('ingredient_tracer.html', ingredients=ingredients)

@app.route("/audit-data", methods=["POST"])
def audit_data():
    print("Accessed /audit-data route")

    connection, cursor = db_conn()
    from flask import request
    from flask import jsonify
    from psycopg2 import sql

    # Fetch form data
    uuid = request.form.get("auditDataInput")
    print(uuid)

    query = sql.SQL("SELECT * FROM query_all_tables_by_uid({})").format(sql.Literal(uuid))

    # Execute the query
    cursor.execute(query)
    audit_data_data = [row[0] for row in cursor.fetchall()]

    print(audit_data_data)

    return render_template('audit_data.html', audit_data_data=audit_data_data)

@app.route('/customs-lodgements-form', methods=["POST"])
def customs_lodgements_form():
    print("Loading customs lodgements form")

    return render_template('customs_lodgements.html')

@app.route('/customs-lodgements', methods=['POST'])
def customs_lodgements():
    print("Processing customs lodgements submission")
    from initialize import db_conn
    connection, cursor = db_conn()
    
    # Get form data
    date_period = request.form.get("date_period")
    lodged_volume = float(request.form.get("lodged_volume"))
    lodged_abv = float(request.form.get("lodged_abv"))

    # Calculate lal
    lal = lodged_volume * lodged_abv / 100
    
    # Calculate the number of bottles - only using Wildflower Gin for now
    bottles = round(lodged_volume / 0.7, 3)
    
    insert_data(table_name='customs_lodgements', audit_action='Adding customs lodgement', date_period=date_period, lodged_volume=lodged_volume, lodged_abv=lodged_abv, lal=lal, bottles=bottles)
    
    return render_template('index.html')

@app.route("/view-customs-lodgements", methods=["POST"])
def view_customs_lodgements():
    print("Accessed /view-customs-lodgements route")

    connection, cursor = db_conn()

    cursor.execute("SELECT date_period, lodged_volume, lodged_abv, lal, bottles FROM customs_lodgements ORDER BY date_period DESC;")
    customs_lodgements = cursor.fetchall()

    return render_template('view_customs_lodgements.html', customs_lodgements=customs_lodgements)

@app.route("/ingredient-tracer", methods=["POST"])
def ingredient_tracer():
    print("Accessed /ingredient-tracer route")

    connection, cursor = db_conn()

    # Fetch form data
    ingredient_names = request.form.getlist("ingredients")

    # create a list of dictionaries to store the tracing information
    trace_results = []

    #if ingredient_name:
    # Trace the ingredient through flavor batches
    # Map ingredients to ingredients_code lists
    if ingredient_names:
        for ingredient_name in ingredient_names:
            if ingredient_name:
                cursor.execute("SELECT DISTINCT ingredients_code FROM purchases_ingredients WHERE ingredients_code IS NOT NULL AND ingredients_code <> 'None' AND ingredients LIKE %s;", ('%' + ingredient_name + '%',))
                ingredient_codes = [row[0] for row in cursor.fetchall() if row[0] is not None]

                for ingredient_code in ingredient_codes:
                    if ingredient_code:
                        # Initialize sets to store unique associated data
                        flavor_batches = set()
                        cursor.execute("SELECT DISTINCT flavor_batch FROM product_actions_flavors WHERE flavor_batch IS NOT NULL AND flavor_batch <> 'None' AND ingredient_codes LIKE %s;", ('%' + ingredient_code + '%',))
                        flavor_batches.update([row[0] for row in cursor.fetchall() if row[0] is not None])

                        # Initialize sets to store unique associated data
                        vat_batches = set()
                        bottle_batches = set()
                        sales = set()
                        
                        # Select suppliers
                        cursor.execute("SELECT DISTINCT supplier FROM purchases_ingredients WHERE ingredients_code IS NOT NULL AND ingredients_code <> 'None' AND ingredients_code LIKE %s;", ('%' + ingredient_code + '%',))
                        ingredient_supplier = [row[0] for row in cursor.fetchall() if row[0] is not None]

                        # Select order size
                        cursor.execute("SELECT DISTINCT ingredients_amount FROM purchases_ingredients WHERE ingredients_code IS NOT NULL AND ingredients_code <> 'None' AND ingredients_code LIKE %s;", ('%' + ingredient_code + '%',))
                        ingredient_size = [row[0] for row in cursor.fetchall() if row[0] is not None]

                        # Select purchase dates - approx
                        cursor.execute("SELECT DISTINCT date FROM purchases_ingredients WHERE ingredients_code IS NOT NULL AND ingredients_code <> 'None' AND ingredients_code LIKE %s;", ('%' + ingredient_code + '%',))
                        ingredient_entry_date = [row[0] for row in cursor.fetchall() if row[0] is not None]
                        formatted_entry_date = ingredient_entry_date[0].strftime("%Y-%m-%d") if ingredient_entry_date else ""

                        # Select expiry dates
                        cursor.execute("SELECT DISTINCT ingredients_expiry FROM purchases_ingredients WHERE ingredients_code IS NOT NULL AND ingredients_code <> 'None' AND ingredients_code LIKE %s;", ('%' + ingredient_code + '%',))
                        ingredient_expiry = [row[0] for row in cursor.fetchall() if row[0] is not None]
                        formatted_expiry = ingredient_expiry[0].strftime("%Y-%m-%d") if ingredient_expiry else ""

                        # Update vat_batch holding flavor_batches
                        for flavor_batch in flavor_batches:
                            if flavor_batch:
                                cursor.execute("SELECT DISTINCT vat_batch FROM product_actions_flavor_vat WHERE vat_batch IS NOT NULL AND vat_batch <> '' AND flavor_batch LIKE %s;", ('%' + flavor_batch + '%',))
                                vat_batches.update([row[0] for row in cursor.fetchall() if row[0] is not None])

                        # Update bottle_batch holding vat_batch
                        for vat_batch in vat_batches:
                            if vat_batch:
                                cursor.execute("SELECT DISTINCT bottle_batch FROM product_actions_bottling WHERE bottle_batch IS NOT NULL AND bottle_batch <> 'None' AND vat_batch LIKE %s;", ('%' + vat_batch + '%',))
                                bottle_batches.update([row[0] for row in cursor.fetchall() if row[0] is not None])

                        # Update sales for bottle_batch
                        for bottle_batch in bottle_batches:
                            if bottle_batch:
                                cursor.execute("SELECT DISTINCT buyer FROM sales_product WHERE bottle_batch IS NOT NULL AND bottle_batch <> 'None' AND bottle_batch = %s;", ('{' + bottle_batch + '}',))
                                sales.update([row[0] for row in cursor.fetchall() if row[0] is not None])

                        # Create a dictionary representing the current data
                        result_data = {
                            'ingredient': ingredient_name,
                            'supplier': str(ingredient_supplier[0]) if ingredient_supplier else "",
                            'quantity': str(ingredient_size[0]) if ingredient_size else "",
                            'entry_date': formatted_entry_date,
                            'expiry': formatted_expiry,
                            'ingredient_codes': ingredient_code,
                            'flavor_batches': list(flavor_batches),  # Convert sets to lists
                            'vat_batches': list(vat_batches),
                            'bottle_batches': list(bottle_batches),
                            'sales': list(sales),
                        }

                        # Append the result_data dictionary to trace_results
                        trace_results.append(result_data)

    return render_template('ingredient_tracer_rusults.html', trace_results=trace_results)

@app.route('/alcohol-dilution-calc-form', methods=["POST"])
def alcohol_dilution_calc_form():
    print("Accessed /alcohol-dilution-calc-form route")

    return render_template('alcohol_dilution_calc.html')

@app.route('/alcohol-dilution-calc', methods=["POST"])
def alcohol_dilution_calc():
    print("Accessed /alcohol-dilution-calc route")

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/alcohol-dilution-calc-form-from-volume', methods=["POST"])
def alcohol_dilution_calc_form_from_volume():
    print("Accessed /alcohol-dilution-calc-form-from-volume route")

    return render_template('alcohol_dilution_calc_from_volume.html')

@app.route('/alcohol-dilution-calc-from-volume', methods=["POST"])
def alcohol_dilution_calc_from_volume():
    print("Accessed /alcohol-dilution-calc-from-volume route")

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/alcohol-starting-abv-form', methods=["POST"])
def alcohol_starting_abv_form():
    print("Accessed /alcohol-starting-abv-form route")

    return render_template('alcohol_starting_abv.html')

@app.route('/alcohol-starting-abv', methods=["POST"])
def alcohol_starting_abv():
    print("Accessed /alcohol-starting-abv route")

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/alcohol-final-abv-form', methods=["POST"])
def alcohol_final_abv_form():
    print("Accessed /alcohol-final-abv-form route")

    return render_template('alcohol_final_abv.html')

@app.route('/alcohol-final-abv', methods=["POST"])
def alcohol_final_abv():
    print("Accessed /alcohol-final-abv route")

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/alcohol-mix-abv-form', methods=["POST"])
def alcohol_mix_abv_form():
    print("Accessed /alcohol-mix-abv-form route")

    return render_template('alcohol_mix_abv.html')

@app.route('/alcohol-mix-abv', methods=["POST"])
def alcohol_mix_abv():
    print("Accessed /alcohol-mix-abv route")

    # Redirect back to the index page
    return render_template('index.html')

@app.route('/mass-calculations-form', methods=['POST'])
def mass_calculations_form():
    print("Accessed /mass-calculations-form route")

    # redirect to mass calc form
    return render_template('mass_calculations.html')

@app.route('/mass-calculations', methods=['POST'])
def mass_calculations():
    print("Accessed /mass-calculations route")

    # redirect to index page
    return render_template('index.html')

@app.route('/spirits-fortification-form', methods=['POST'])
def spirits_fortification_form():
    print("Accessed /spirits-fortification-form route")

    # redirect to spirits foritifcation calc form
    return render_template('spirits_fortification.html')

@app.route('/spirits-fortification', methods=['POST'])
def spirits_fortification():
    print("Accessed /spirits_fortification route")

    # redirect to index page
    return render_template('index.html')

@app.route('/growth-projection-form', methods=['POST'])
def growth_projection_form():
    print("Accessed /growth-projection-form route")

    # Redirect to growth-projection-form form
    return render_template('growth_projection_form.html')

@app.route('/growth-projection', methods=['POST'])
def growth_projection():
    print("Accessed /growth-projection form")

    # redirect to index page
    return render_template('index.html')

@app.route('/revenue-report', methods=['POST'])
def revenue_report():
    print("Accessed /revenue-report route")
    from datetime import datetime
    connection, cursor = db_conn()

    # Extract monthly data
    cursor.execute("""
        WITH unique_invoices AS (
            SELECT DISTINCT ON (notes) 
                date,
                notes,
                invoice_total,
                invoice_gst,
                -- Extract total bottles from products JSONB
                (SELECT COALESCE(SUM((value->>'quantity')::int), 0)
                 FROM jsonb_each(products->'products')) as total_bottles,
                -- Extract total duty from products JSONB
                (SELECT COALESCE(SUM((value->>'duty_amount')::numeric), 0)
                 FROM jsonb_each(products->'products')) as total_duty
            FROM sales_product
            WHERE notes LIKE '%INV%'
            AND products IS NOT NULL
        )
        SELECT 
            date_trunc('month', date) as month,
            SUM(total_bottles) as bottles,
            SUM(total_duty) as duty,
            SUM(invoice_total) as revenue,
            SUM(invoice_gst) as gst
        FROM unique_invoices
        GROUP BY date_trunc('month', date)
        ORDER BY month DESC;
    """)
    monthly_data = cursor.fetchall()

    # Define cost dictionaries
    fixed_recurring_costs = {
        'premise': {
            'base': 331.86,
            'gst': 331.86 * 0.15,
            'frequency': 'weekly'  # weekly or monthly
        },
        'gmail': {
            'base': 25.63,
            'gst': 25.63 * 0.15,
            'frequency': 'monthly'
        },
        'bank_fees': {
            'base': 24.35,
            'gst': 24.35 * 0.15,
            'frequency': 'monthly'
        },
        'website': {
            'base': 47.828,
            'gst': 47.828 * 0.15,
            'frequency': 'monthly'
        },
        'accountants': {
            'base': 230.00,
            'gst': 230.00 * 0.15,
            'frequency': 'monthly'
        }
    }

    fixed_one_off_costs = {
        'bottles': {
            'base': 1.10,
        },
        'importing_bottles': {
            'base': 0.73,
        },
        'labels': {
            'base': 0.77,
        },
        'case_boxes': {
            'base': 0.41,
        },
        'ethanol': {
            'base': 2.35,
        },
        'heatshrink': {
            'base': 0.23,
        },
        'botanicals': {
            'base': 0.87,
        },
        'corks': {
            'base': 0.40,
        }
    }

    variable_costs = {
        'power': {
            'base': 130.00,
            'gst': 130.00 * 0.15,
        }
    }

    monthly_revenue = []
    total_bottles = 0
    total_duty = 0
    total_revenue = 0
    total_gst = 0
    total_costs = 0
    total_profit = 0

    # Process monthly data
    for row in monthly_data:
        month, bottles, duty, revenue, gst = row
        
        # Handle null values
        bottles = int(bottles) if bottles else 0
        duty = float(duty) if duty else 0
        revenue = float(revenue) if revenue else 0
        gst = float(gst) if gst else 0

        # Calculate monthly fixed recurring costs
        monthly_recurring_costs = {}
        for name, cost in fixed_recurring_costs.items():
            # Only include premise costs from Feb 2025 onwards
            if name == 'premise':
                if month.date() >= datetime(2025, 2, 1).date():
                    monthly_amount = cost['base'] + cost.get('gst', 0)
                    if cost.get('frequency') == 'weekly':
                        monthly_amount *= (52/12)  # Convert weekly to monthly
                    monthly_recurring_costs[name] = monthly_amount
                else:
                    monthly_recurring_costs[name] = 0
            else:
                monthly_amount = cost['base'] + cost.get('gst', 0)
                if cost.get('frequency') == 'weekly':
                    monthly_amount *= (52/12)  # Convert weekly to monthly
                monthly_recurring_costs[name] = monthly_amount

        # Calculate one-off costs per bottle
        one_off_costs_per_bottle = {} 
        for name, cost in fixed_one_off_costs.items():
            total_cost = cost['base']  # Calculate per bottle cost
            cost_per_bottle = total_cost * 1.15  # Add GST
            one_off_costs_per_bottle[name] = {
                'cost_per_bottle': cost_per_bottle,
            }

        # Calculate total fixed costs for this month
        total_fixed_costs = sum(monthly_recurring_costs.values())

        # Calculate one-off costs based on bottles sold
        one_off_costs = {}
        # Add duty
        duty_per_bottle = duty / bottles if bottles > 0 else 0
        one_off_costs['duty'] = duty

        # Add other one-off costs based on per-bottle rates
        for name, cost_info in one_off_costs_per_bottle.items():
            one_off_costs[name] = cost_info['cost_per_bottle'] * bottles

        # Calculate one-off costs per bottle
        one_off_costs_per_bottle_no_gst = {} 
        for name, cost in fixed_one_off_costs.items():
            total_cost = cost['base']  # Calculate per bottle cost
            cost_per_bottle = total_cost
            one_off_costs_per_bottle_no_gst[name] = {
                'cost_per_bottle': cost_per_bottle,
            }

        one_off_costs_no_gst = {}
        one_off_costs_no_gst['duty'] = duty

        # Add other one-off costs based on per-bottle rates
        for name, cost_info in one_off_costs_per_bottle_no_gst.items():
            one_off_costs_no_gst[name] = cost_info['cost_per_bottle'] * bottles

        # Calculate variable costs for this month
        monthly_variable_costs = {}
        for name, cost in variable_costs.items():
            # Only include power costs from Feb 2025 onwards
            if name == 'power':
                if month.date() >= datetime(2025, 2, 1).date():
                    base_cost = cost.get('base', 0) + cost.get('gst', 0)
                    monthly_variable_costs[name] = base_cost
                else:
                    monthly_variable_costs[name] = 0
            else:
                base_cost = cost.get('base', 0) + cost.get('gst', 0)
                monthly_variable_costs[name] = base_cost

        # Calculate total costs
        total_one_off_costs = sum(one_off_costs.values())
        total_one_off_costs_no_gst = sum(one_off_costs_no_gst.values())
        total_variable_costs = sum(monthly_variable_costs.values())
        monthly_costs = total_fixed_costs + total_one_off_costs_no_gst + total_variable_costs
        monthly_costs_minus_bottle_costs = total_fixed_costs + total_variable_costs

        # Calculate cost breakdown
        business_costs_one_off = {}
        # Add duty (duty is already without GST)
        business_costs_one_off['duty'] = duty

        # Add other one-off costs based on base rates (without GST)
        for name, cost in fixed_one_off_costs.items():
            business_costs_one_off[name] = cost['base'] * bottles

        cost_breakdown = {
            'fixed_costs': monthly_recurring_costs,
            'one_off_costs': one_off_costs,  # Now includes duty
            'variable_costs': monthly_variable_costs,
            'duty_per_bottle': duty_per_bottle,
            'one_off_costs_no_gst': one_off_costs_no_gst,
            'one_off_costs_per_bottle_no_gst': one_off_costs_per_bottle_no_gst,
            'total_one_off_costs_no_gst': total_one_off_costs_no_gst,
            'business_costs_one_off': business_costs_one_off  # New field for Business Costs & Profitability table
        }

        # Calculate profit (no need to subtract duty again since it's in costs)
        monthly_profit = revenue - gst - monthly_costs

        # Calculate profit margin
        profit_margin = (monthly_profit / revenue * 100) if revenue > 0 else 0

        # Update totals
        total_bottles += bottles
        total_duty += duty
        total_revenue += revenue
        total_gst += gst
        total_costs += monthly_costs
        total_profit += monthly_profit

        monthly_revenue.append({
            'month': month.strftime('%B %Y'),
            'bottles': bottles,
            'duty': duty,
            'revenue': revenue,
            'gst': gst,
            'costs': monthly_costs,
            'cost_breakdown': cost_breakdown,
            'profit': monthly_profit,
            'profit_margin': profit_margin
        })

    # Add total row
    if monthly_revenue:
        overall_profit_margin = (total_profit / (total_revenue - total_gst) * 100) if total_revenue > 0 else 0
        monthly_revenue.append({
            'month': 'Total',
            'bottles': total_bottles,
            'duty': total_duty,
            'revenue': total_revenue,
            'gst': total_gst,
            'costs': total_costs,
            'profit': total_profit,
            'profit_margin': overall_profit_margin
        })

        # Calculate monthly target values
        # Calculate average revenue per bottle (excluding GST)
        total_bottles_for_avg = 0
        total_revenue_for_avg = 0
        total_gst_for_avg = 0
        for month in monthly_revenue:
            if month['month'] != 'Total' and month['bottles'] > 0:
                total_bottles_for_avg += month['bottles']
                total_revenue_for_avg += month['revenue']
                total_gst_for_avg += month['gst']
        
        actual_revenue_per_bottle = (total_revenue_for_avg - total_gst_for_avg) / total_bottles_for_avg if total_bottles_for_avg > 0 else 42.95

        # Calculate total monthly fixed costs using the dictionaries
        print("\n=== Monthly Fixed Costs Breakdown ===")
        targets_fixed_recurring_costs = 0
        for name, cost in fixed_recurring_costs.items():
            monthly_amount = (cost['base'] + cost.get('gst', 0)) * (52/12 if cost.get('frequency') == 'weekly' else 1)
            targets_fixed_recurring_costs += monthly_amount
            print(f"{name}: ${monthly_amount:.2f} (Base: ${cost['base']:.2f}, GST: ${cost.get('gst', 0):.2f}, Frequency: {cost.get('frequency', 'monthly')})")

        print("\n=== Variable Costs Breakdown ===")
        targets_fixed_variable_costs = 0
        for name, cost in variable_costs.items():
            monthly_amount = cost.get('base', 0) + cost.get('gst', 0)
            targets_fixed_variable_costs += monthly_amount
            print(f"{name}: ${monthly_amount:.2f} (Base: ${cost.get('base', 0):.2f}, GST: ${cost.get('gst', 0):.2f})")

        targets_monthly_costs_minus_bottle_costs = targets_fixed_recurring_costs + targets_fixed_variable_costs
        print(f"\nTotal Monthly Costs (minus bottle costs): ${targets_monthly_costs_minus_bottle_costs:.2f}")
        print(f"  - Fixed Recurring Costs: ${targets_fixed_recurring_costs:.2f}")
        print(f"  - Variable Costs: ${targets_fixed_variable_costs:.2f}")

        # Calculate total variable cost per bottle
        per_wildflower_bottle_duty_cost = 67.22 * (0.7 * 0.44)
        total_costs_per_bottle = sum(cost_info['cost_per_bottle'] for cost_info in one_off_costs_per_bottle_no_gst.values()) + per_wildflower_bottle_duty_cost
        print(f"total_costs_per_bottle: {total_costs_per_bottle}")

        # Calculate profit per bottle
        profit_per_bottle = actual_revenue_per_bottle - total_costs_per_bottle
        print(f"profit_per_bottle: {profit_per_bottle}")

        # Calculate required bottles and revenue
        required_bottles = round(targets_monthly_costs_minus_bottle_costs / profit_per_bottle, 0) if profit_per_bottle > 0 else 0
        required_revenue = required_bottles * (actual_revenue_per_bottle * 1.15)
        print(f"required_bottles: {required_bottles}")
        print(f"required_revenue: {required_revenue}")

        # Add monthly targets to the template context
        monthly_targets = {
            'required_bottles': required_bottles,
            'required_revenue': required_revenue,
            'revenue_per_bottle': actual_revenue_per_bottle
        }

        # Calc bottle order savings tracker using the dictionaries
        order_tracker_per_bottle = fixed_one_off_costs['bottles']['base'] * 1.15
        order_tracker_per_bottle_importing = fixed_one_off_costs['importing_bottles']['base'] * 1.15
        cost_of_bottles_for_10k_order_tracker = (order_tracker_per_bottle + order_tracker_per_bottle_importing) * 10000
        print(f"cost_of_bottles_for_10k_order_tracker: {cost_of_bottles_for_10k_order_tracker}")

        bottle_sales_for_10k_order_tracker = cost_of_bottles_for_10k_order_tracker / profit_per_bottle
        print(f"bottle_sales_for_10k_order_tracker: {bottle_sales_for_10k_order_tracker}")

        # Calc lease tracker

    cursor.close()
    return render_template('revenue_reporting.html', monthly_revenue=monthly_revenue, monthly_targets=monthly_targets, bottle_sales_for_10k_order_tracker=bottle_sales_for_10k_order_tracker)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)
        print("Scheduler is running...")

@app.route('/download-invoice/<invoice_number>')
def download_invoice(invoice_number):
    """Route to download invoice PDF files"""
    print(f"Download request for invoice: {invoice_number}")
    
    try:
        # Sanitize the invoice number to prevent directory traversal attacks
        import os
        from werkzeug.utils import secure_filename
        
        # Clean the invoice number
        safe_invoice_number = secure_filename(invoice_number)
        
        # Construct the file path
        invoice_path = os.path.join('invoices', f"{safe_invoice_number}.pdf")
        
        # Check if file exists
        if not os.path.exists(invoice_path):
            print(f"Invoice file not found: {invoice_path}")
            return jsonify({"error": "Invoice file not found"}), 404
        
        print(f"Serving invoice file: {invoice_path}")
        
        # Serve the PDF file
        from flask import send_file
        return send_file(
            invoice_path,
            as_attachment=True,
            download_name=f"{safe_invoice_number}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error downloading invoice {invoice_number}: {e}")
        return jsonify({"error": f"Error downloading invoice: {str(e)}"}), 500

@app.route('/view-invoice/<invoice_number>')
def view_invoice(invoice_number):
    """Route to view invoice PDF files in browser"""
    print(f"View request for invoice: {invoice_number}")
    
    try:
        # Sanitize the invoice number
        import os
        from werkzeug.utils import secure_filename
        
        safe_invoice_number = secure_filename(invoice_number)
        invoice_path = os.path.join('invoices', f"{safe_invoice_number}.pdf")
        
        # Check if file exists
        if not os.path.exists(invoice_path):
            print(f"Invoice file not found: {invoice_path}")
            return jsonify({"error": "Invoice file not found"}), 404
        
        print(f"Viewing invoice file: {invoice_path}")
        
        # Serve the PDF file for viewing (not as download)
        from flask import send_file
        return send_file(
            invoice_path,
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error viewing invoice {invoice_number}: {e}")
        return jsonify({"error": f"Error viewing invoice: {str(e)}"}), 500

@app.route('/check-invoice/<invoice_number>')
def check_invoice_exists(invoice_number):
    """Route to check if an invoice PDF file exists"""
    print(f"Checking if invoice exists: {invoice_number}")
    
    try:
        # Sanitize the invoice number
        import os
        from werkzeug.utils import secure_filename
        
        safe_invoice_number = secure_filename(invoice_number)
        invoice_path = os.path.join('invoices', f"{safe_invoice_number}.pdf")
        
        # Check if file exists
        file_exists = os.path.exists(invoice_path)
        file_size = os.path.getsize(invoice_path) if file_exists else 0
        
        print(f"Invoice {invoice_number} exists: {file_exists}, size: {file_size} bytes")
        
        return jsonify({
            "exists": file_exists,
            "invoice_number": invoice_number,
            "file_size": file_size,
            "file_path": invoice_path if file_exists else None
        })
        
    except Exception as e:
        print(f"Error checking invoice {invoice_number}: {e}")
        return jsonify({"error": f"Error checking invoice: {str(e)}"}), 500

@app.route('/crm-update-customer-field', methods=['POST'])
def crm_update_customer_field():
    print("Accessed /crm-update-customer-field route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        field = data.get('field')
        value = data.get('value')
        
        if not all([customer_name, field, value]):
            return jsonify({
                "success": False,
                "message": "Missing required fields"
            }), 400
        
        # Define allowed fields to prevent SQL injection
        allowed_fields = ['customer_notes', 'customer_email', 'customer_phone', 'customer_address', 'primary_contact']
        
        if field not in allowed_fields:
            return jsonify({
                "success": False,
                "message": f"Field '{field}' is not allowed"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Update the customer field
            update_query = f"UPDATE crm_customers SET {field} = %s WHERE customer = %s"
            cursor.execute(update_query, (value, customer_name))
            
            if cursor.rowcount == 0:
                return jsonify({
                    "success": False,
                    "message": f"Customer '{customer_name}' not found"
                }), 404
            
            # Field updated successfully - no need for additional audit logging
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": f"Successfully updated {field} for {customer_name}",
                "field": field,
                "value": value
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_update_customer_field: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-update-follow-up-task', methods=['POST'])
def crm_update_follow_up_task():
    print("Accessed /crm-update-follow-up-task route")
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        
        if not task_id:
            return jsonify({
                "success": False,
                "message": "Missing task_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Build dynamic update query based on provided fields
            update_fields = []
            update_values = []
            
            if 'notes' in data:
                update_fields.append("follow_up_notes = %s")
                update_values.append(data['notes'])
            
            if 'due_date' in data:
                update_fields.append("follow_up_date = %s")
                update_values.append(data['due_date'])
            
            if 'priority' in data:
                update_fields.append("follow_up_priority = %s")
                update_values.append(data['priority'])
            
            if 'type' in data:
                update_fields.append("follow_up_type = %s")
                update_values.append(data['type'])
            
            if 'status' in data:
                update_fields.append("follow_up_status = %s")
                update_values.append(data['status'])
            
            if not update_fields:
                return jsonify({
                    "success": False,
                    "message": "No fields to update"
                }), 400
            
            # Add task_id to values for WHERE clause
            update_values.append(task_id)
            
            # Build and execute update query
            update_query = f"UPDATE crm_follow_ups SET {', '.join(update_fields)} WHERE id = %s"
            cursor.execute(update_query, update_values)
            
            if cursor.rowcount == 0:
                return jsonify({
                    "success": False,
                    "message": f"Task with id {task_id} not found"
                }), 404
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Task updated successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_update_follow_up_task: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-delete-follow-up-task', methods=['POST'])
def crm_delete_follow_up_task():
    print("Accessed /crm-delete-follow-up-task route")
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        
        if not task_id:
            return jsonify({
                "success": False,
                "message": "Missing task_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Delete the follow-up task
            cursor.execute("DELETE FROM crm_follow_ups WHERE id = %s", (task_id,))
            
            if cursor.rowcount == 0:
                return jsonify({
                    "success": False,
                    "message": f"Task with id {task_id} not found"
                }), 404
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Task deleted successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_delete_follow_up_task: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-create-follow-up-task', methods=['POST'])
def crm_create_follow_up_task():
    print("Accessed /crm-create-follow-up-task route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        follow_up_task = data.get('follow_up_task')
        follow_up_date = data.get('follow_up_date')
        follow_up_priority = data.get('follow_up_priority')
        follow_up_type = data.get('follow_up_type')
        follow_up_status = data.get('follow_up_status')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not follow_up_task:
            return jsonify({
                "success": False,
                "message": "Missing follow_up_task"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Insert follow-up task into crm_follow_ups table
            insert_data(table_name='crm_follow_ups', 
                       audit_action='Create Follow-up Task', 
                       customer=customer_name, 
                       follow_up_date=follow_up_date, 
                       follow_up_priority=follow_up_priority, 
                       follow_up_status=follow_up_status, 
                       follow_up_notes=follow_up_task, 
                       follow_up_type=follow_up_type)
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Follow-up task created successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_create_follow_up_task: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-create-call-log', methods=['POST'])
def crm_create_call_log():
    print("Accessed /crm-create-call-log route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer')
        log_date = data.get('log_date')
        log_type = data.get('log_type')
        log_notes = data.get('log_notes')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer"
            }), 400
        
        if not log_notes:
            return jsonify({
                "success": False,
                "message": "Missing log_notes"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Insert call log into crm_logs table
            insert_data(table_name='crm_logs', 
                       audit_action=f'Recording call logs for {customer_name}', 
                       customer=customer_name, 
                       log_date=log_date, 
                       log_type=log_type, 
                       log_notes=log_notes)
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Call log created successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_create_call_log: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-add-contact', methods=['POST'])
def crm_add_contact():
    print("=== CRM ADD CONTACT ROUTE HIT ===")
    print(f"Request method: {request.method}")
    print(f"Request content type: {request.content_type}")
    print(f"Request data: {request.get_data()}")
    
    try:
        data = request.get_json()
        print(f"Parsed JSON data: {data}")
        
        customer_name = data.get('customer_name')
        contact_name = data.get('contact_name')
        contact_email = data.get('contact_email')
        contact_phone = data.get('contact_phone')
        contact_notes = data.get('contact_notes')
        
        print(f"Extracted values - customer_name: {customer_name}, contact_name: {contact_name}")
        
        if not customer_name:
            print("ERROR: Missing customer_name")
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_name:
            print("ERROR: Missing contact_name")
            return jsonify({
                "success": False,
                "message": "Missing contact_name"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            print(f"Querying database for customer: {customer_name}")
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            print(f"Database result: {result}")
            
            if not result:
                print(f"ERROR: Customer {customer_name} not found in database")
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            print(f"Current contacts: {current_contacts}")
            
            # Generate new contact ID (highest existing ID + 1, or 1 if none exist)
            max_id = max([contact.get('id', 0) for contact in current_contacts], default=0)
            new_contact_id = max_id + 1
            print(f"New contact ID: {new_contact_id}")
            
            # Create new contact object
            new_contact = {
                'id': new_contact_id,
                'name': contact_name,
                'email': contact_email or '',
                'phone': contact_phone or '',
                'notes': contact_notes or ''
            }
            print(f"New contact object: {new_contact}")
            
            # Add new contact to the list
            current_contacts.append(new_contact)
            print(f"Updated contacts list: {current_contacts}")
            
            # Update the contacts JSONB column
            print(f"Updating database with new contacts data...")
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(current_contacts), customer_name))
            
            connection.commit()
            print("Database update successful!")
            
            return jsonify({
                "success": True,
                "message": "Contact added successfully",
                "contact_id": new_contact_id
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_add_contact: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-update-contact', methods=['POST'])
def crm_update_contact():
    print("Accessed /crm-update-contact route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        contact_id = data.get('contact_id')
        contact_name = data.get('contact_name')
        contact_email = data.get('contact_email')
        contact_phone = data.get('contact_phone')
        contact_notes = data.get('contact_notes')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_id:
            return jsonify({
                "success": False,
                "message": "Missing contact_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            
            if not result:
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            
            # Find and update the contact
            contact_found = False
            for contact in current_contacts:
                if contact.get('id') == contact_id:
                    contact['name'] = contact_name
                    contact['email'] = contact_email or ''
                    contact['phone'] = contact_phone or ''
                    contact['notes'] = contact_notes or ''
                    contact_found = True
                    break
            
            if not contact_found:
                return jsonify({
                    "success": False,
                    "message": f"Contact with id {contact_id} not found"
                }), 404
            
            # Update the contacts JSONB column
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(current_contacts), customer_name))
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Contact updated successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_update_contact: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-delete-contact', methods=['POST'])
def crm_delete_contact():
    print("Accessed /crm-delete-contact route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        contact_id = data.get('contact_id')
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_id:
            return jsonify({
                "success": False,
                "message": "Missing contact_id"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            
            if not result:
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            
            # Remove the contact and reorder remaining contacts
            updated_contacts = []
            for i, contact in enumerate(current_contacts):
                if contact.get('id') != contact_id:
                    # Reorder contacts with sequential IDs starting from 1
                    contact['id'] = len(updated_contacts) + 1
                    updated_contacts.append(contact)
            
            # Update the contacts JSONB column
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(updated_contacts), customer_name))
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Contact deleted successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_delete_contact: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-reorder-contacts', methods=['POST'])
def crm_reorder_contacts():
    print("Accessed /crm-reorder-contacts route")
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        contact_id = data.get('contact_id')
        direction = data.get('direction')  # 'up' or 'down'
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        if not contact_id:
            return jsonify({
                "success": False,
                "message": "Missing contact_id"
            }), 400
        
        if direction not in ['up', 'down']:
            return jsonify({
                "success": False,
                "message": "Invalid direction. Must be 'up' or 'down'"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Get current contacts JSONB data
            cursor.execute("SELECT contacts FROM crm_customers WHERE customer = %s", (customer_name,))
            result = cursor.fetchone()
            
            if not result:
                return jsonify({
                    "success": False,
                    "message": f"Customer {customer_name} not found"
                }), 404
            
            current_contacts = result[0] if result[0] else []
            
            # Find the contact index
            contact_index = None
            for i, contact in enumerate(current_contacts):
                if contact.get('id') == contact_id:
                    contact_index = i
                    break
            
            if contact_index is None:
                return jsonify({
                    "success": False,
                    "message": f"Contact with id {contact_id} not found"
                }), 404
            
            # Check if move is valid
            if direction == 'up' and contact_index == 0:
                return jsonify({
                    "success": False,
                    "message": "Contact is already at the top"
                }), 400
            
            if direction == 'down' and contact_index == len(current_contacts) - 1:
                return jsonify({
                    "success": False,
                    "message": "Contact is already at the bottom"
                }), 400
            
            # Swap contacts
            if direction == 'up':
                current_contacts[contact_index], current_contacts[contact_index - 1] = \
                    current_contacts[contact_index - 1], current_contacts[contact_index]
            else:  # down
                current_contacts[contact_index], current_contacts[contact_index + 1] = \
                    current_contacts[contact_index + 1], current_contacts[contact_index]
            
            # Update the contacts JSONB column
            cursor.execute("UPDATE crm_customers SET contacts = %s WHERE customer = %s", 
                         (json.dumps(current_contacts), customer_name))
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Contact reordered successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_reorder_contacts: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

@app.route('/crm-mark-task-completed', methods=['POST'])
def crm_mark_task_completed():
    print("Accessed /crm-mark-task-completed route")
    
    try:
        data = request.get_json()
        task_id = data.get('task_id')
        customer_name = data.get('customer_name')
        
        if not task_id:
            return jsonify({
                "success": False,
                "message": "Missing task_id"
            }), 400
        
        if not customer_name:
            return jsonify({
                "success": False,
                "message": "Missing customer_name"
            }), 400
        
        from initialize import db_conn
        connection, cursor = db_conn()
        
        try:
            # Update the task status to 'completed' in crm_follow_ups table
            update_query = """
                UPDATE crm_follow_ups 
                SET follow_up_status = 'completed' 
                WHERE id = %s AND customer = %s
            """
            cursor.execute(update_query, (task_id, customer_name))
            
            if cursor.rowcount == 0:
                return jsonify({
                    "success": False,
                    "message": "Task not found or already completed"
                }), 404
            
            connection.commit()
            
            return jsonify({
                "success": True,
                "message": "Task marked as completed successfully"
            })
            
        except Exception as e:
            print(f"❌ Database error: {e}")
            connection.rollback()
            return jsonify({
                "success": False,
                "message": f"Database error: {str(e)}"
            }), 500
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
                
    except Exception as e:
        print(f"❌ Error in crm_mark_task_completed: {e}")
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}"
        }), 500

if __name__ == '__main__':
    # Start the scheduler in a separate thread
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.start()

    # Run the app on all available network interfaces (0.0.0.0)
    # Use configuration for host, port, and debug settings
    app.run(
        host=config.host,
        port=config.port,
        debug=config.debug,
        ssl_context=('tls/wb_cert.pem', 'tls/wb_cert.key')
    )
