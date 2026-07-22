# Prize Winners Display Configuration

## Overview
The home page displays a fixed number of the most recent prize winners (by default, the last 50), instead of a date-window ("last N days/months") cutoff.

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
    'WINNERS_DISPLAY_COUNT': 50,  # Number of most recent winners to show
}
```

### How to Change the Number of Winners Shown
1. Open `survey_app/settings.py`
2. Find the `LUCKY_DRAW_CONFIG` dictionary
3. Change the value of `WINNERS_DISPLAY_COUNT` to your desired number of winners

Example:
```python
'WINNERS_DISPLAY_COUNT': 100,  # Show the last 100 winners
```

## Implementation Details

### Backend Changes
- **HomePageView** (`surveys/views_frontend.py`): Fetches the most recent `WINNERS_DISPLAY_COUNT` winners, ordered by `-created_at`, with no date cutoff
- **Template**: Updated to display dynamic winner data with fallback content

### Frontend Changes
- **Template** (`templates/frontpage/index.html`): 
  - Dynamic title: "Last {{ winners_display_count }} Prize Winners"
  - Dynamic winner cards with user names, prizes, and dates
  - Fallback content when no winners exist

### Features
- **Configurable Count**: Easily change how many winners to show
- **Dynamic Content**: Shows actual winners from the database
- **Profile Pictures**: Displays user profile pictures if available
- **Fallback Content**: Shows placeholder content when no winners exist
- **Responsive Design**: Maintains existing styling and layout

## Usage
1. Configure `WINNERS_DISPLAY_COUNT` in settings
2. Winners will automatically appear when users win prizes
3. The section always shows the most recent winners up to that count, regardless of how old they are

## Testing
To verify the implementation:
1. Check that the home page loads without errors
2. Verify the title shows the correct winner count
3. Confirm winners appear when they exist in the database
4. Verify fallback content appears when no winners exist
