# Prize Winners Display Configuration

## Overview
The home page now displays prize winners for a configurable number of days from the last winning date, instead of the static "Last Month's Prize Winners" section.

## Configuration

### Settings
In `survey_app/settings.py`, the following configuration has been added:

```python
LUCKY_DRAW_CONFIG = {
    'SURVEYS_REQUIRED': 3,
    'NUMBER_RANGE_START': 1,
    'NUMBER_RANGE_END': 49,
    'PRIZES': [
        "₹1000 Amazon Voucher",
        "₹500 Flipkart Voucher", 
        "₹250 BookMyShow Voucher"
    ],
    'WINNERS_DISPLAY_DAYS': 30,  # Number of days to show winners from last winning date
}
```

### How to Change the Display Period
To change how many days of winners are displayed:

1. Open `survey_app/settings.py`
2. Find the `LUCKY_DRAW_CONFIG` dictionary
3. Change the value of `WINNERS_DISPLAY_DAYS` to your desired number of days

Example:
```python
'WINNERS_DISPLAY_DAYS': 60,  # Show winners from last 60 days
```

## Implementation Details

### Backend Changes
- **HomePageView** (`surveys/views_frontend.py`): Updated to fetch recent winners based on the configured days
- **Template**: Updated to display dynamic winner data with fallback content

### Frontend Changes
- **Template** (`templates/frontpage/index.html`): 
  - Dynamic title: "Last {{ winners_display_days }} Days' Prize Winners"
  - Dynamic winner cards with user names, prizes, and dates
  - Fallback content when no winners exist

### Features
- **Configurable Display Period**: Easily change how many days of winners to show
- **Dynamic Content**: Shows actual winners from the database
- **Profile Pictures**: Displays user profile pictures if available
- **Fallback Content**: Shows placeholder content when no winners exist
- **Responsive Design**: Maintains existing styling and layout

## Usage
1. Configure the display period in settings
2. Winners will automatically appear when users win prizes
3. The section will update dynamically based on the configured timeframe

## Testing
To verify the implementation:
1. Check that the home page loads without errors
2. Verify the title shows the correct number of days
3. Confirm winners appear when they exist in the database
4. Verify fallback content appears when no winners exist
