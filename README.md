# EKZ Smart Meter Daily Power Usage Scraper for Home Assistant

This script allows you to scrape your daily energy consumption data from the myEKZ website using Python and Selenium. The script retrieves the data table, extracts the relevant information, and outputs the data in JSON format. The data is provided in kilowatt hours (kWh) in the range of every 15 minutes and is updated every 24 hours.

The Python script retrieves the power usage data from an external API or database and returns it in a JSON format.

## Requirements

To use this script, you will need:

- Python 3
- Selenium 3.141.0
- BeautifulSoup 4.9.3
- ChromeDriver (if using a local Chrome installation)
- Valid username & password for the EKZ website

## Installation and Configuration

To use the Daily Power Grid Usage scraper, follow these steps:

    1. Clone this repository.
    2. Create a virtual environment in the repository directory and activate it.
    3. Install any required dependencies using pip.
