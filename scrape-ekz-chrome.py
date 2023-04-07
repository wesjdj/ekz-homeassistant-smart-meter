import os
import time
import csv
import json

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def log_in(driver, url, username, password):
    driver.get(url)

    username_input = driver.find_element(By.ID, "username")
    password_input = driver.find_element(By.ID, "password")
    login_button = driver.find_element(By.ID, "kc-login")

    username_input.send_keys(username)
    password_input.send_keys(password)
    login_button.click()

def download_csv(driver, download_button_text, download_folder):
    # Wait for the download button to be visible
    try:
        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, f'//button[contains(text(), "{download_button_text}")]'))
        )
    except TimeoutError:
        print("Timeout while waiting for the download button")
        driver.quit()
        return

    # Scroll the download button into view
    download_button = driver.find_element(By.XPATH, f'//button[contains(text(), "{download_button_text}")]')
    driver.execute_script("arguments[0].scrollIntoView();", download_button)

    # Add a small delay before clicking
    time.sleep(2)

    # Click the download button
    # download_button.click()
    driver.execute_script("arguments[0].click();", download_button)

    # Wait for the download to complete
    time.sleep(5)  # Adjust the waiting time if necessary

def csv_to_json(csv_file_path):
    data = []
    with open(csv_file_path, encoding="utf-8") as csvfile:
        # Skip the first 3 lines
        for _ in range(3):
            csvfile.readline()

        reader = csv.DictReader(csvfile, delimiter=';')
        
        for row in reader:
            data.append(row)
    return data


def format_data_for_home_assistant(data):
    formatted_data = []
    for row in data:
        entry = {
            "date": row["Zeitraum"],
            "ht_value": float(row["HT [kWh]"]),
            "nt_value": float(row["NT [kWh]"]),
            "total_value": float(row["Gesamt [kWh]"])
        }
        formatted_data.append(entry)
    return formatted_data


def get_most_recent_csv(download_folder):
    csv_files = [f for f in os.listdir(download_folder) if f.endswith(".csv")]
    if not csv_files:
        return None

    most_recent_csv = max(csv_files, key=lambda f: os.path.getctime(os.path.join(download_folder, f)))
    return os.path.join(download_folder, most_recent_csv)

if __name__ == "__main__":
    verbrauch_url = "https://my.ekz.ch/verbrauch/"
    login_url = "https://my.ekz.ch/login/"  # Replace with the actual login URL
    download_button_text = "Tabellendaten herunterladen"  # Update the button class if necessary
    username = ""
    password = ""
    download_folder = os.path.abspath("downloads")  # Change the folder if necessary

    chrome_options = Options()
    # Uncomment the next line to run Chrome in headless mode
    chrome_options.add_argument("--headless")

    # Set up the download folder for Chrome
    prefs = {
        "download.default_directory": download_folder,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=chrome_options)

    log_in(driver, login_url, username, password)

    # Navigate to the verbrauch URL after logging in
    driver.get(verbrauch_url)

    download_csv(driver, download_button_text, download_folder)

    # Close the browser
    driver.quit()

    print(f"CSV file downloaded to {download_folder}")

    # Get the path of the most recently downloaded CSV file
    csv_file_path = get_most_recent_csv(download_folder)

    if csv_file_path:
        # Convert the CSV data to JSON
        data = csv_to_json(csv_file_path)

        # Format the data for Home Assistant
        formatted_data = format_data_for_home_assistant(data)

        # Print the formatted data
        print("Formatted data for Home Assistant:")
        print(json.dumps(formatted_data, indent=2))
    else:
        print("No CSV file found")
