from playwright.sync_api import sync_playwright
import time
import sys

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()
        
        print("1. Going to landing page...")
        page.goto("https://www.adrreports.eu", wait_until="networkidle")
        print(f"   URL: {page.url}")
        
        print("2. Clicking HUMAN...")
        human = page.get_by_text("HUMAN", exact=True)
        if human.count() > 0:
            human.click()
            page.wait_for_load_state("networkidle")
            print(f"   URL: {page.url}")
        else:
            print("   HUMAN button not found.")
            
        print("3. Clicking English 'en' link...")
        en_link = page.get_by_role("link", name="en European database")
        if en_link.count() > 0:
            en_link.click()
            page.wait_for_load_state("networkidle")
            print(f"   URL: {page.url}")
        else:
            print("   English link not found.")
            
        print("4. Clicking 'Search' link...")
        search_link = page.query_selector("a[href='search.html']")
        if search_link:
            search_link.click()
            page.wait_for_load_state("networkidle")
            print(f"   URL: {page.url}")
            
            # Handle search disclaimer if it appears
            if "disclaimer.html" in page.url:
                print("   Search disclaimer detected. Looking for Accept button...")
                accept = page.query_selector("input[value*='Accept'], button:has-text('Accept'), a:has-text('Accept')")
                if accept:
                    accept.click()
                    page.wait_for_load_state("networkidle")
                    print(f"   URL after accepting disclaimer: {page.url}")
                else:
                    print("   Could not find Accept button on search disclaimer.")
                    
            # Now on search.html, click Substances link
            print("4b. Clicking 'Substance Search' link on search.html...")
            subst_search = page.query_selector("a[href='search_subst.html']")
            if subst_search:
                subst_search.click()
                page.wait_for_load_state("networkidle")
                print(f"   URL after Substance Search: {page.url}")
            else:
                print("   Substance search link not found on search.html.")
        else:
            print("   Search link not found on index.html.")
                
        print("5. Clicking 'M' for Metformin via JS...")
        page.evaluate("showSubstanceTable('m')")
        print("   Waiting for substances list to populate...")
        time.sleep(5)
        
        print("6. Looking for METFORMIN link...")
        # Check all links on the page after the JS call
        links = page.query_selector_all("a")
        metformin = None
        for l in links:
            t = l.inner_text().strip().upper()
            if "METFORMIN" == t or "METFORMIN" in t:
                metformin = l
                print(f"   Found candidate: {t}")
                if t == "METFORMIN":
                    break
        
        if metformin:
            print(f"   METFORMIN HTML: {page.evaluate('(e) => e.outerHTML', metformin)}")
            print("   Clicking METFORMIN...")
            # Click and wait for navigation or new page
            with context.expect_page() as new_page_info:
                metformin.click()
            
            new_page = new_page_info.value
            new_page.wait_for_load_state("networkidle")
            print(f"   New Page URL: {new_page.url}")
            print(f"   New Page Title: {new_page.title()}")
            
            print("7. Looking for content on OBIEE page...")
            # Dump more text to get the Sex table
            full_text = new_page.inner_text('body')
            print(f"   OBIEE Page Text (First 2000 chars): {full_text[:2000]}")
            
            # Find the Sex table specifically
            if "Sex" in full_text:
                sex_start = full_text.find("Number of individual cases by Sex")
                if sex_start != -1:
                    print(f"   Sex Distribution Fragment: {full_text[sex_start:sex_start+500]}")
            
            accept = new_page.query_selector("input[value*='Accept'], button:has-text('Accept'), a:has-text('Accept')")
            if accept:
                print("   Found Accept button. Clicking it...")
                accept.click()
                new_page.wait_for_load_state("networkidle")
                time.sleep(10) # Dashboard is slow
                print(f"   URL after ACCEPT: {new_page.url}")
                
                # DUMP FRAME INFORMATION
                print("\n--- DASHBOARD STRUCTURE ---")
                print(f"Number of frames: {len(new_page.frames)}")
                for i, frame in enumerate(new_page.frames):
                    print(f"Frame {i}: url={frame.url}")
                    # ... (rest of scan logic)
                    try:
                        # Search for common OBIEE selectors
                        tabs = frame.query_selector_all(".DashboardTabSelected, .DashboardTab")
                        if tabs:
                            print(f"   Tabs found in frame {i}:")
                            for t in tabs:
                                print(f"      - {t.inner_text().strip()}")
                        
                        tables = frame.query_selector_all("table.PTChildPivotTable")
                        if tables:
                            print(f"   Table with counts found in frame {i} (PTChildPivotTable)")
                            for t in tables[:1]:
                                rows = t.query_selector_all("tr")[:10]
                                for r in rows:
                                    cells = [c.inner_text().strip() for c in r.query_selector_all("td, th")]
                                    print(f"         {cells}")
                        
                        # Fallback: dump ANY table if no PTChildPivotTable
                        if not tables:
                            any_tables = frame.query_selector_all("table")
                            if any_tables:
                                print(f"   Found {len(any_tables)} general tables in frame {i}. Printing first row of each:")
                                for t in any_tables[:5]:
                                    row = t.query_selector("tr")
                                    if row:
                                        print(f"      {row.inner_text().strip()}")
                    except Exception as e:
                        print(f"   Error scanning frame {i}: {e}")
            else:
                print("   Accept button not found on substance landing.")
        else:
            print("   METFORMIN not found in list.")
            # Dump first 20 links for debugging
            print("   First 20 links for debugging:")
            for l in links[:20]:
                print(f"      - {l.inner_text().strip()}")
            
        browser.close()

if __name__ == '__main__':
    main()
