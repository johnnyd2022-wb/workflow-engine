import os
import re
import fitz  # PyMuPDF

def debug_invoice_extraction(file_path):
    """
    Debug function to see exactly what's happening with product extraction
    for invoices INV-147 to INV-174 that are missing product_name values.
    """
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
    
    try:
        # Read the PDF content
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        
        print(f"=" * 80)
        print(f"DEBUGGING: {os.path.basename(file_path)}")
        print(f"=" * 80)
        
        # Print full raw text
        print("\n--- FULL RAW TEXT ---")
        print(text)
        print("--- END FULL RAW TEXT ---\n")
        
        # Split by PAYMENT ADVICE if multiple invoices
        invoice_sections = text.split("PAYMENT ADVICE")[1:] if "PAYMENT ADVICE" in text else [text]
        
        for idx, section in enumerate(invoice_sections):
            print(f"\n{'='*60}")
            print(f"INVOICE SECTION {idx + 1}")
            print(f"{'='*60}")
            
            # Look for the products section specifically
            print("\n--- SEARCHING FOR PRODUCTS SECTION ---")
            products_pattern = r"Amount\s+NZD\s*\n(.*?)(?=Subtotal|TOTAL)"
            products_match = re.search(products_pattern, section, re.DOTALL)
            
            if products_match:
                products_text = products_match.group(1).strip()
                print("✅ FOUND PRODUCTS SECTION:")
                print(f"'{products_text}'")
                
                # Split into lines and show what we're working with
                lines = [line.strip() for line in products_text.split('\n') if line.strip()]
                print(f"\n📋 PARSED LINES ({len(lines)} total):")
                for i, line in enumerate(lines):
                    print(f"  {i}: '{line}'")
                
                # Try to process lines in groups of 4
                print(f"\n🔍 PROCESSING IN GROUPS OF 4:")
                i = 0
                product_count = 0
                while i < len(lines):
                    if i + 3 < len(lines):
                        name_line = lines[i]
                        qty_line = lines[i + 1] if i + 1 < len(lines) else "MISSING"
                        price_line = lines[i + 2] if i + 2 < len(lines) else "MISSING" 
                        amount_line = lines[i + 3] if i + 3 < len(lines) else "MISSING"
                        
                        print(f"  Group {i//4 + 1}:")
                        print(f"    Name: '{name_line}'")
                        print(f"    Qty:  '{qty_line}'")
                        print(f"    Price: '{price_line}'")
                        print(f"    Amount: '{amount_line}'")
                        
                        # Test if this looks like a product name
                        if re.match(r'^\d+\.?\d*$', name_line):
                            print(f"    ❌ SKIPPED: Looks like a number, not a product name")
                            i += 1
                            continue
                        
                        # Test the cleaning logic
                        clean_name = re.sub(r'\s+-\s+x\d+$', '', name_line)
                        print(f"    After removing 'x1' suffix: '{clean_name}'")
                        
                        # Test the wildflower/solstice extraction
                        if 'wildflower' in clean_name.lower():
                            final_name = 'wildflower'
                        elif 'solstice' in clean_name.lower():
                            final_name = 'solstice'
                        else:
                            final_name = clean_name.lower().strip()
                        
                        print(f"    Final product name: '{final_name}'")
                        
                        # Try to parse quantity, unit price, amount
                        try:
                            quantity = float(qty_line)
                            unit_price = float(price_line)
                            amount = float(amount_line)
                            print(f"    ✅ SUCCESSFULLY PARSED: qty={quantity}, price={unit_price}, amount={amount}")
                            product_count += 1
                        except ValueError as e:
                            print(f"    ❌ PARSING ERROR: {e}")
                        
                        print()
                        i += 4
                    else:
                        print(f"  ❌ Not enough lines remaining for group starting at {i}")
                        break
                
                print(f"📊 TOTAL PRODUCTS FOUND: {product_count}")
                
            else:
                print("❌ NO PRODUCTS SECTION FOUND")
                print("Looking for pattern: Amount\\s+NZD\\s*\\n(.*?)(?=Subtotal|TOTAL)")
                
                # Let's see if we can find "Amount NZD" at all
                if "Amount NZD" in section:
                    print("✅ Found 'Amount NZD' in text")
                    # Find where it appears
                    amount_nzd_pos = section.find("Amount NZD")
                    context_start = max(0, amount_nzd_pos - 100)
                    context_end = min(len(section), amount_nzd_pos + 200)
                    print(f"Context around 'Amount NZD':")
                    print(f"'{section[context_start:context_end]}'")
                else:
                    print("❌ 'Amount NZD' not found in section")
                
                # Look for other patterns that might indicate products
                print("\n🔍 LOOKING FOR ALTERNATIVE PATTERNS:")
                if "Description" in section:
                    print("✅ Found 'Description'")
                if "Quantity" in section:
                    print("✅ Found 'Quantity'")
                if "Unit Price" in section:
                    print("✅ Found 'Unit Price'")
                if "Subtotal" in section:
                    print("✅ Found 'Subtotal'")
                if "TOTAL" in section:
                    print("✅ Found 'TOTAL'")
                    
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

# Example usage
if __name__ == "__main__":
    # Test with one of the problematic invoices
    invoice_file = "./invoices/INV-147.pdf"  # Change to your actual path
    
    print("Invoice Product Extraction Debugger")
    print("=" * 50)
    
    debug_invoice_extraction(invoice_file)
    
    print("\n" + "=" * 50)
    print("To use this script:")
    print("1. Update 'invoice_file' variable with the problematic PDF path")  
    print("2. Run: python debug_invoice.py")
    print("3. Check the output to see why products aren't being extracted") 