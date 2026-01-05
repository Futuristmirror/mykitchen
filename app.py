import streamlit as st
import requests
from recipe_scrapers import scrape_html
from recipe_scrapers._exceptions import WebsiteNotImplementedError
import validators
import json
import os
import re
from datetime import datetime
from fractions import Fraction
from bs4 import BeautifulSoup

# Configure the page
st.set_page_config(
    page_title="MyKitchen",
    page_icon="🍳",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# File paths for saving data
FAVORITES_FILE = os.path.join(os.path.dirname(__file__), "favorites.json")
CATEGORIES_FILE = os.path.join(os.path.dirname(__file__), "categories.json")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "session.json")

# Session expiry time (1 hour in seconds)
SESSION_EXPIRY_SECONDS = 3600

# Default categories
DEFAULT_CATEGORIES = ["Cookies", "Casseroles", "Soups", "Salads", "Desserts", "Main Dishes", "Appetizers", "Breakfast", "Uncategorized"]

def load_favorites():
    """Load favorites from file"""
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_favorites(favorites):
    """Save favorites to file"""
    with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
        json.dump(favorites, f, indent=2, ensure_ascii=False)

def load_categories():
    """Load categories from file, sorted alphabetically with Uncategorized at end"""
    if os.path.exists(CATEGORIES_FILE):
        try:
            with open(CATEGORIES_FILE, 'r', encoding='utf-8') as f:
                cats = json.load(f)
        except:
            cats = DEFAULT_CATEGORIES.copy()
    else:
        cats = DEFAULT_CATEGORIES.copy()

    # Sort alphabetically, but keep "Uncategorized" at the end
    other_cats = sorted([c for c in cats if c != "Uncategorized"], key=str.lower)
    if "Uncategorized" in cats:
        other_cats.append("Uncategorized")
    return other_cats

def save_categories(categories):
    """Save categories to file"""
    with open(CATEGORIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(categories, f, indent=2, ensure_ascii=False)

def load_session():
    """Load session state from file (persists across browser refreshes)"""
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r', encoding='utf-8') as f:
                session = json.load(f)
                # Check if session has expired (older than 1 hour)
                saved_time = session.get('timestamp', 0)
                if datetime.now().timestamp() - saved_time > SESSION_EXPIRY_SECONDS:
                    # Session expired, return empty
                    return None
                return session
        except:
            return None
    return None

def save_session():
    """Save current session state to file"""
    session_data = {
        'timestamp': datetime.now().timestamp(),
        'view': st.session_state.get('view', 'main'),
        'recipe': st.session_state.get('recipe'),
        'source_url': st.session_state.get('source_url'),
        'ingredient_checks': st.session_state.get('ingredient_checks', {}),
        'step_checks': st.session_state.get('step_checks', {}),
        'ingredient_edits': st.session_state.get('ingredient_edits', {}),
        'view_mode': st.session_state.get('view_mode', 'scroll'),
    }
    try:
        with open(SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
    except:
        pass  # Silently fail if can't save

def restore_session():
    """Restore session state from file if available"""
    session = load_session()
    if session:
        if 'view' not in st.session_state and session.get('view'):
            st.session_state['view'] = session['view']
        if 'recipe' not in st.session_state and session.get('recipe'):
            st.session_state['recipe'] = session['recipe']
        if 'source_url' not in st.session_state and session.get('source_url'):
            st.session_state['source_url'] = session['source_url']
        if 'ingredient_checks' not in st.session_state and session.get('ingredient_checks'):
            st.session_state['ingredient_checks'] = session['ingredient_checks']
        if 'step_checks' not in st.session_state and session.get('step_checks'):
            st.session_state['step_checks'] = session['step_checks']
        if 'ingredient_edits' not in st.session_state and session.get('ingredient_edits'):
            st.session_state['ingredient_edits'] = session['ingredient_edits']
        if 'view_mode' not in st.session_state and session.get('view_mode'):
            st.session_state['view_mode'] = session['view_mode']

def get_recipe_id(recipe):
    """Generate a unique ID for a recipe based on title"""
    return recipe['title'].lower().replace(' ', '_')[:50]

def decimal_to_fraction(decimal_str):
    """Convert a decimal number to a nice fraction string"""
    try:
        num = float(decimal_str)

        # If it's a whole number, return as int
        if num == int(num):
            return str(int(num))

        # Common cooking fractions to check against
        common_fractions = {
            0.125: '1/8',
            0.25: '1/4',
            0.333: '1/3',
            0.375: '3/8',
            0.5: '1/2',
            0.625: '5/8',
            0.666: '2/3',
            0.667: '2/3',
            0.75: '3/4',
            0.875: '7/8',
        }

        # Check if it's close to a common fraction
        whole_part = int(num)
        frac_part = num - whole_part

        # Find closest common fraction
        for decimal, fraction in common_fractions.items():
            if abs(frac_part - decimal) < 0.02:  # Within 2% tolerance
                if whole_part > 0:
                    return f"{whole_part} {fraction}"
                return fraction

        # If no common fraction matches, use Fraction class
        frac = Fraction(num).limit_denominator(8)
        if frac.denominator == 1:
            return str(frac.numerator)
        if frac.numerator > frac.denominator:
            whole = frac.numerator // frac.denominator
            remainder = frac.numerator % frac.denominator
            if remainder == 0:
                return str(whole)
            return f"{whole} {remainder}/{frac.denominator}"
        return f"{frac.numerator}/{frac.denominator}"
    except:
        return decimal_str

def clean_ingredient(ingredient):
    """Clean up ingredient text, converting decimals to fractions"""
    # Pattern to find decimal numbers (including long ones like 0.6666666)
    decimal_pattern = r'(\d*\.\d+)'

    def replace_decimal(match):
        return decimal_to_fraction(match.group(1))

    return re.sub(decimal_pattern, replace_decimal, ingredient)

def clean_ingredients(ingredients):
    """Clean all ingredients in a list"""
    return [clean_ingredient(ing) for ing in ingredients]

def split_embedded_steps(instructions):
    """Split instructions that have embedded numbered steps like '1. First step 2. Second step'"""
    if not instructions:
        return instructions

    cleaned_steps = []
    for step in instructions:
        # Check if this step contains embedded numbered steps (like "1. ... 2. ... 3. ...")
        # Pattern: number followed by period and space, occurring multiple times
        if re.search(r'\d+\.\s+.+\d+\.\s+', step):
            # Split on pattern like "1. ", "2. ", etc. but keep the content
            parts = re.split(r'(?=\d+\.\s+)', step)
            for part in parts:
                part = part.strip()
                if part:
                    # Remove the leading number and period (e.g., "1. " becomes just the text)
                    cleaned_part = re.sub(r'^\d+\.\s*', '', part).strip()
                    if cleaned_part:
                        cleaned_steps.append(cleaned_part)
        else:
            # Single step - just add it (strip any leading number if present)
            cleaned_step = re.sub(r'^\d+\.\s*', '', step).strip()
            if cleaned_step:
                cleaned_steps.append(cleaned_step)

    return cleaned_steps if cleaned_steps else instructions

# Custom CSS for mobile-friendly design
st.markdown("""
<style>
    /* Mobile-first design */
    .stApp {
        max-width: 500px;
        margin: 0 auto;
    }

    /* Recipe card styling */
    .recipe-card {
        background: white;
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }

    /* Time badges */
    .time-badge {
        display: inline-block;
        background: #f0f2f6;
        padding: 8px 16px;
        border-radius: 20px;
        margin: 4px;
        font-size: 14px;
    }

    /* Category badge */
    .category-badge {
        display: inline-block;
        background: #e8f4e8;
        color: #2e7d32;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 12px;
        margin-left: 8px;
    }

    /* Step cards - works in both light and dark mode */
    .step-card {
        background: rgba(128, 128, 128, 0.1);
        border-left: 4px solid #ff6b6b;
        padding: 16px;
        margin: 12px 0;
        border-radius: 0 8px 8px 0;
        color: inherit;
    }

    .step-card span {
        color: inherit;
    }

    .step-number {
        background: #ff6b6b;
        color: white;
        width: 28px;
        height: 28px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        margin-right: 12px;
    }

    /* Dark mode support */
    @media (prefers-color-scheme: dark) {
        .step-card {
            background: rgba(255, 255, 255, 0.1);
        }
        .time-badge {
            background: rgba(255, 255, 255, 0.15);
            color: inherit;
        }
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Input styling */
    .stTextInput input {
        border-radius: 12px;
        padding: 12px 16px;
        font-size: 16px;
    }

    /* Button styling */
    .stButton > button {
        width: 100%;
        border-radius: 12px;
        padding: 12px 24px;
        font-size: 16px;
        font-weight: 600;
        background: #ff6b6b;
        color: white;
        border: none;
    }

    .stButton > button:hover {
        background: #ee5a5a;
    }

    /* Checkbox styling - gray out and cross off checked items */
    /* Only apply to ingredient/step checkboxes, not to GF toggle */
    .stCheckbox:has(input:checked) label p {
        color: #999 !important;
        text-decoration: line-through !important;
    }

    .stCheckbox:has(input:checked) label span {
        color: #999 !important;
        text-decoration: line-through !important;
    }

    /* Override for GF checkbox - no strikethrough */
    div[data-testid="stCheckbox"]:has(input[aria-label*="Gluten Free"]) label p,
    div[data-testid="stCheckbox"]:has(input[aria-label*="Gluten Free"]) label span {
        color: inherit !important;
        text-decoration: none !important;
    }

    /* Edit pencil button */
    .edit-btn {
        background: none;
        border: none;
        cursor: pointer;
        font-size: 14px;
        padding: 2px 6px;
        opacity: 0.5;
        transition: opacity 0.2s;
    }

    .edit-btn:hover {
        opacity: 1;
    }

    /* Edited ingredient styling */
    .edited-ingredient {
        color: #d32f2f !important;
    }

    @media (prefers-color-scheme: dark) {
        .edited-ingredient {
            color: #ff6b6b !important;
        }
    }

    /* Favorite button */
    .favorite-btn {
        background: #ffd700 !important;
    }

    /* Comments box */
    .stTextArea textarea {
        border-radius: 12px;
        font-size: 14px;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 8px 16px;
    }
</style>
""", unsafe_allow_html=True)

def extract_schema_recipe(html, url):
    """Extract recipe from Schema.org JSON-LD data (fallback for unsupported sites)"""
    soup = BeautifulSoup(html, 'html.parser')

    # Look for JSON-LD schema data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)

            # Handle array of schemas
            if isinstance(data, list):
                for item in data:
                    if item.get('@type') == 'Recipe':
                        data = item
                        break
                else:
                    continue

            # Handle @graph structure
            if '@graph' in data:
                for item in data['@graph']:
                    if item.get('@type') == 'Recipe':
                        data = item
                        break
                else:
                    continue

            if data.get('@type') != 'Recipe':
                continue

            # Extract ingredients
            ingredients = data.get('recipeIngredient', [])
            if not ingredients:
                ingredients = data.get('ingredients', [])

            # Extract instructions
            instructions = []
            raw_instructions = data.get('recipeInstructions', [])
            if isinstance(raw_instructions, str):
                instructions = [raw_instructions]
            elif isinstance(raw_instructions, list):
                for inst in raw_instructions:
                    if isinstance(inst, str):
                        instructions.append(inst)
                    elif isinstance(inst, dict):
                        text = inst.get('text', inst.get('name', ''))
                        if text:
                            instructions.append(text)

            # Extract times
            def parse_duration(duration):
                if not duration:
                    return None
                # Parse ISO 8601 duration (PT30M, PT1H30M, etc.)
                match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', str(duration))
                if match:
                    hours = int(match.group(1) or 0)
                    mins = int(match.group(2) or 0)
                    return hours * 60 + mins
                return None

            # Extract image
            image = data.get('image')
            if isinstance(image, list):
                image = image[0] if image else None
            if isinstance(image, dict):
                image = image.get('url')

            recipe = {
                'title': data.get('name', 'Recipe'),
                'image': image,
                'prep_time': parse_duration(data.get('prepTime')),
                'cook_time': parse_duration(data.get('cookTime')),
                'total_time': parse_duration(data.get('totalTime')),
                'servings': data.get('recipeYield'),
                'ingredients': clean_ingredients(ingredients),
                'instructions': instructions,
                'source_url': url,
                'category': 'Uncategorized',
            }

            # Only return if we got useful data
            if recipe['ingredients'] or recipe['instructions']:
                return recipe

        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    return None

def extract_weekendbakery_recipe(html, url):
    """Extract recipe from Weekend Bakery website (custom parser)"""
    soup = BeautifulSoup(html, 'html.parser')

    # Get title from h1 or page title
    title_tag = soup.find('h1', class_='entry-title') or soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else "Recipe"

    # Find the main content area
    content = soup.find('div', class_='entry-content') or soup.find('article') or soup

    # Extract ingredients - look for lists after "Ingredients" heading or common patterns
    ingredients = []

    # Method 1: Look for ingredient-related content in list items
    for ul in content.find_all('ul'):
        items = ul.find_all('li')
        for item in items:
            text = item.get_text(strip=True)
            # Check if it looks like an ingredient (has measurement patterns)
            if re.search(r'\d+\s*g\b|\d+\s*ml\b|\d+\s*tsp|\d+\s*tbsp|\d+\s*cup|gram|ounce|\d+\s*oz', text, re.IGNORECASE):
                ingredients.append(text)

    # Method 2: Look for short paragraphs that start with measurements (Weekend Bakery style)
    if not ingredients:
        for p in content.find_all('p'):
            text = p.get_text(strip=True)
            # Short paragraphs starting with a number followed by g/ml/etc are likely ingredients
            if len(text) < 150 and re.match(r'^\d+\s*(g|ml|tsp|tbsp|cup)\s+', text, re.IGNORECASE):
                ingredients.append(text)
            # Also catch "X egg" style ingredients
            elif len(text) < 100 and re.match(r'^\d+\s+egg', text, re.IGNORECASE):
                ingredients.append(text)

    # Method 3: Look for paragraphs with multiple ingredients on one line
    if not ingredients:
        for p in content.find_all('p'):
            text = p.get_text(strip=True)
            if re.search(r'\d+\s*g\s+\w+.*\d+\s*g\s+\w+', text):
                parts = re.split(r'(?=\d+\s*g\s+)', text)
                for part in parts:
                    part = part.strip()
                    if part and re.search(r'\d+\s*g\b', part):
                        ingredients.append(part)

    # Extract instructions - look for numbered steps or paragraphs with cooking verbs
    instructions = []

    # Look for ordered lists
    for ol in content.find_all('ol'):
        for li in ol.find_all('li'):
            text = li.get_text(strip=True)
            if text and len(text) > 20:  # Skip very short items
                instructions.append(text)

    # If no ordered list, look for paragraphs with step-like content
    if not instructions:
        cooking_verbs = r'\b(mix|combine|add|stir|fold|knead|roll|bake|proof|preheat|shape|cut|cover|refrigerate|let|place|brush|repeat)\b'
        for p in content.find_all('p'):
            text = p.get_text(strip=True)
            if len(text) > 50 and re.search(cooking_verbs, text, re.IGNORECASE):
                instructions.append(text)

    # Try to find an image
    image = None
    img_tag = content.find('img')
    if img_tag:
        image = img_tag.get('src') or img_tag.get('data-src')

    # Only return if we found some useful content
    if ingredients or instructions:
        return {
            'title': title,
            'image': image,
            'prep_time': None,
            'cook_time': None,
            'total_time': None,
            'servings': None,
            'ingredients': clean_ingredients(ingredients),
            'instructions': instructions,
            'source_url': url,
            'category': 'Uncategorized',
        }

    return None

def extract_generic_recipe(html, url):
    """Last-resort generic parser for blog-style recipe pages"""
    soup = BeautifulSoup(html, 'html.parser')

    # Get title
    title_tag = soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else "Recipe"

    # Find main content (try common content containers)
    content = (soup.find('article') or
               soup.find('div', class_=re.compile(r'content|post|entry', re.I)) or
               soup.find('main') or
               soup.body)

    if not content:
        return None

    # Extract all list items and paragraphs
    ingredients = []
    instructions = []

    # Ingredient patterns
    ingredient_pattern = r'\d+\s*(g|kg|ml|l|oz|lb|cup|cups|tsp|tbsp|teaspoon|tablespoon|gram|grams|ounce|ounces)\b'

    # Collect all list items
    for li in content.find_all('li'):
        text = li.get_text(strip=True)
        if text and len(text) > 3:
            if re.search(ingredient_pattern, text, re.IGNORECASE):
                ingredients.append(text)

    # Collect instruction-like paragraphs
    cooking_verbs = r'\b(mix|combine|add|stir|fold|knead|roll|bake|proof|preheat|shape|cut|cover|refrigerate|let|place|brush|repeat|cook|heat|simmer|boil|fry|pour|whisk)\b'

    for p in content.find_all('p'):
        text = p.get_text(strip=True)
        if len(text) > 60 and re.search(cooking_verbs, text, re.IGNORECASE):
            instructions.append(text)

    # Find image
    image = None
    for img in content.find_all('img'):
        src = img.get('src') or img.get('data-src')
        if src and not re.search(r'logo|icon|avatar|button', src, re.IGNORECASE):
            image = src
            break

    if ingredients or instructions:
        return {
            'title': title,
            'image': image,
            'prep_time': None,
            'cook_time': None,
            'total_time': None,
            'servings': None,
            'ingredients': clean_ingredients(ingredients),
            'instructions': instructions,
            'source_url': url,
            'category': 'Uncategorized',
        }

    return None

def fetch_recipe(url):
    """Fetch and parse recipe from URL"""
    try:
        # Validate URL
        if not validators.url(url):
            return None, "That doesn't look like a valid web address. Please paste the full URL including https://"

        # Fetch the page
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        html = response.text

        # Helper to safely call scraper methods (some throw exceptions instead of returning None)
        def safe_get(method):
            try:
                result = method()
                return result if result else None
            except:
                return None

        # Try the recipe-scrapers library first
        try:
            scraper = scrape_html(html, org_url=url)

            # Get ingredients and clean them up
            raw_ingredients = safe_get(scraper.ingredients) or []
            cleaned_ingredients = clean_ingredients(raw_ingredients)

            recipe = {
                'title': safe_get(scraper.title) or "Recipe",
                'image': safe_get(scraper.image),
                'prep_time': safe_get(scraper.prep_time),
                'cook_time': safe_get(scraper.cook_time),
                'total_time': safe_get(scraper.total_time),
                'servings': safe_get(scraper.yields),
                'ingredients': cleaned_ingredients,
                'instructions': safe_get(scraper.instructions_list) or [],
                'source_url': url,
                'category': 'Uncategorized',
            }

            return recipe, None

        except WebsiteNotImplementedError:
            # Site not directly supported - try fallback parsers
            # 1. Try Schema.org structured data
            recipe = extract_schema_recipe(html, url)
            if recipe:
                return recipe, None

            # 2. Try Weekend Bakery specific parser (works for similar blog formats)
            recipe = extract_weekendbakery_recipe(html, url)
            if recipe:
                return recipe, None

            # 3. Try generic recipe extraction
            recipe = extract_generic_recipe(html, url)
            if recipe:
                return recipe, None

            return None, "This website isn't fully supported yet, and we couldn't find the recipe data. Try a different recipe site."

    except requests.exceptions.Timeout:
        return None, "The website took too long to respond. Please try again."
    except requests.exceptions.RequestException:
        return None, "Couldn't reach that website. Please check the link and try again."
    except Exception as e:
        return None, "Couldn't find a recipe on that page. Make sure you're pasting a link to a specific recipe, not just the homepage."

def format_time(minutes):
    """Format minutes into readable time"""
    if not minutes:
        return None
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours} hr"
    return f"{hours} hr {mins} min"

def render_ingredients(recipe, recipe_id):
    """Render the ingredients section with checkboxes and edit functionality"""
    # Initialize states if not exists
    if 'ingredient_checks' not in st.session_state:
        st.session_state.ingredient_checks = {}
    if 'edit_mode' not in st.session_state:
        st.session_state.edit_mode = False
    if 'pending_edits' not in st.session_state:
        st.session_state.pending_edits = {}

    # Load favorites to get permanent edits
    favorites = load_favorites()
    is_favorited = recipe_id in favorites

    # Get permanent edits from favorites (saved forever)
    permanent_edits = {}
    if is_favorited:
        permanent_edits = favorites[recipe_id].get('ingredient_edits', {})

    # Edit mode toggle
    st.session_state.edit_mode = st.toggle("Edit mode", value=st.session_state.edit_mode, key=f"edit_toggle_{recipe_id}")

    # Always clean ingredients when displaying (fixes old saved recipes)
    ingredients = clean_ingredients(recipe.get('ingredients', []))

    for i, ingredient in enumerate(ingredients):
        key = f"ing_{recipe_id}_{i}"
        edit_key = str(i)  # Simple index key for storage
        checked = st.session_state.ingredient_checks.get(key, False)

        # Check if this ingredient has been edited (from permanent storage)
        edited_value = permanent_edits.get(edit_key)
        display_text = edited_value if edited_value else ingredient
        is_edited = edited_value is not None and edited_value != ingredient

        if st.session_state.edit_mode:
            # Edit mode - show text input for each ingredient
            input_key = f"input_{edit_key}_{recipe_id}"
            new_value = st.text_input(
                f"Ingredient {i+1}",
                value=display_text,
                key=input_key,
                label_visibility="collapsed"
            )
            # Store the current value in pending edits
            st.session_state.pending_edits[edit_key] = new_value
        else:
            # Normal mode - checkbox with text
            # Build label based on state
            if is_edited:
                label_text = f"🔴 {display_text}"
            else:
                label_text = display_text

            checked_state = st.checkbox(
                label_text,
                value=checked,
                key=key
            )
            st.session_state.ingredient_checks[key] = checked_state

            # Show original text below if edited
            if is_edited:
                st.markdown(f'<p style="color: #999; font-size: 0.8em; margin-top: -10px; margin-left: 28px; font-style: italic;">was: {ingredient}</p>', unsafe_allow_html=True)

    # Save edits permanently when in edit mode
    if st.session_state.edit_mode and is_favorited:
        # Show save button in edit mode
        if st.button("💾 Save Edits", key=f"save_edits_{recipe_id}"):
            # Collect all edits from pending_edits that differ from original
            final_edits = {}
            for i, ingredient in enumerate(ingredients):
                edit_key = str(i)
                pending_value = st.session_state.pending_edits.get(edit_key, ingredient)
                if pending_value != ingredient:
                    final_edits[edit_key] = pending_value

            favorites[recipe_id]['ingredient_edits'] = final_edits
            save_favorites(favorites)
            st.session_state.pending_edits = {}  # Clear pending
            st.success("Edits saved permanently!")
            st.rerun()
    elif not is_favorited and st.session_state.edit_mode:
        st.info("Save this recipe to favorites to keep your edits permanently.")

def render_steps(recipe, recipe_id):
    """Render the steps section with checkboxes"""
    # Initialize step check states if not exists
    if 'step_checks' not in st.session_state:
        st.session_state.step_checks = {}

    # Split any embedded numbered steps (fixes sites that put all steps in one string)
    instructions = split_embedded_steps(recipe.get('instructions', []))

    for i, step in enumerate(instructions, 1):
        key = f"step_{recipe_id}_{i}"
        checked = st.session_state.step_checks.get(key, False)

        # Use checkbox with step number and text as label
        step_label = f"**Step {i}:** {step}"

        new_checked = st.checkbox(
            step_label,
            value=checked,
            key=key
        )
        st.session_state.step_checks[key] = new_checked

def render_comments(recipe, recipe_id, favorites, is_favorited):
    """Render the baker's comments section"""
    # Load existing comments for this recipe if favorited
    existing_comments = ""
    if is_favorited and 'comments' in favorites.get(recipe_id, {}):
        existing_comments = favorites[recipe_id]['comments']

    comments_key = f"comments_{recipe_id}"
    comments = st.text_area(
        "Add your notes, substitutions, or tips for next time:",
        value=existing_comments,
        height=100,
        key=comments_key,
        label_visibility="collapsed",
        placeholder="Add your notes, substitutions, or tips for next time..."
    )

    # Save comments button (only if favorited)
    if is_favorited and comments != existing_comments:
        if st.button("💾 Save Comments", key="save_comments"):
            favorites[recipe_id]['comments'] = comments
            save_favorites(favorites)
            st.success("Comments saved!")

def render_stars(rating):
    """Convert a rating (0-5) to star display"""
    full_stars = int(rating)
    empty_stars = 5 - full_stars
    return "⭐" * full_stars + "☆" * empty_stars

def render_conversions():
    """Render the kitchen conversions chart"""
    st.markdown("### 📐 Kitchen Conversions")

    # Volume conversions table
    st.markdown("**Volume Conversions**")
    volume_html = """
    <style>
    .conv-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 20px; }
    .conv-table th { background-color: #6b8e23; color: white; padding: 8px; text-align: center; }
    .conv-table td { border: 1px solid #ddd; padding: 6px; text-align: center; color: inherit; }
    .conv-table tr:nth-child(even) { background-color: rgba(128, 128, 128, 0.1); }
    .conv-table tr:nth-child(odd) td { background-color: transparent; }
    @media (prefers-color-scheme: dark) {
        .conv-table td { border-color: #444; }
        .conv-table tr:nth-child(even) { background-color: rgba(255, 255, 255, 0.05); }
    }
    </style>
    <table class="conv-table">
    <tr><th>tsp</th><th>tbsp</th><th>fl oz</th><th>cup</th><th>pint</th><th>quart</th><th>gallon</th></tr>
    <tr><td>3</td><td>1</td><td>1/2</td><td>1/16</td><td>1/32</td><td>-</td><td>-</td></tr>
    <tr><td>6</td><td>2</td><td>1</td><td>1/8</td><td>1/16</td><td>1/32</td><td>-</td></tr>
    <tr><td>12</td><td>4</td><td>2</td><td>1/4</td><td>1/8</td><td>1/16</td><td>-</td></tr>
    <tr><td>18</td><td>6</td><td>3</td><td>3/8</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>24</td><td>8</td><td>4</td><td>1/2</td><td>1/4</td><td>1/8</td><td>1/32</td></tr>
    <tr><td>36</td><td>12</td><td>6</td><td>3/4</td><td>-</td><td>-</td><td>-</td></tr>
    <tr><td>48</td><td>16</td><td>8</td><td>1</td><td>1/2</td><td>1/4</td><td>1/16</td></tr>
    <tr><td>96</td><td>32</td><td>16</td><td>2</td><td>1</td><td>1/2</td><td>1/8</td></tr>
    <tr><td>-</td><td>64</td><td>32</td><td>4</td><td>2</td><td>1</td><td>1/4</td></tr>
    <tr><td>-</td><td>256</td><td>128</td><td>16</td><td>8</td><td>4</td><td>1</td></tr>
    </table>
    """
    st.markdown(volume_html, unsafe_allow_html=True)

    # Milliliters section
    st.markdown("**Milliliters**")
    ml_html = """
    <table class="conv-table" style="width: auto; display: inline-block; margin-right: 15px; vertical-align: top;">
    <tr><th>tsp</th><th>ml</th></tr>
    <tr><td>1/2</td><td>2.5</td></tr>
    <tr><td>1</td><td>5</td></tr>
    </table>
    <table class="conv-table" style="width: auto; display: inline-block; margin-right: 15px; vertical-align: top;">
    <tr><th>tbsp</th><th>ml</th></tr>
    <tr><td>1</td><td>15</td></tr>
    </table>
    <table class="conv-table" style="width: auto; display: inline-block; margin-right: 15px; vertical-align: top;">
    <tr><th>oz</th><th>ml</th></tr>
    <tr><td>2</td><td>60</td></tr>
    <tr><td>4</td><td>115</td></tr>
    <tr><td>6</td><td>170</td></tr>
    <tr><td>8</td><td>230</td></tr>
    <tr><td>10</td><td>285</td></tr>
    <tr><td>12</td><td>340</td></tr>
    </table>
    <table class="conv-table" style="width: auto; display: inline-block; vertical-align: top;">
    <tr><th>cup</th><th>ml</th></tr>
    <tr><td>1/4</td><td>60</td></tr>
    <tr><td>1/2</td><td>120</td></tr>
    <tr><td>2/3</td><td>160</td></tr>
    <tr><td>3/4</td><td>180</td></tr>
    <tr><td>1</td><td>240</td></tr>
    </table>
    """
    st.markdown(ml_html, unsafe_allow_html=True)

    # Grams section
    st.markdown("**Grams**")
    grams_html = """
    <table class="conv-table" style="width: auto;">
    <tr><th>oz</th><th>g</th><th>lb</th></tr>
    <tr><td>2</td><td>58</td><td>-</td></tr>
    <tr><td>4</td><td>114</td><td>-</td></tr>
    <tr><td>6</td><td>170</td><td>-</td></tr>
    <tr><td>8</td><td>226</td><td>1/2</td></tr>
    <tr><td>12</td><td>340</td><td>-</td></tr>
    <tr><td>16</td><td>454</td><td>1</td></tr>
    </table>
    """
    st.markdown(grams_html, unsafe_allow_html=True)

def render_photos(recipe, recipe_id, favorites, is_favorited):
    """Render the photo gallery section for saved recipes"""
    if not is_favorited:
        st.info("Save this recipe to favorites to add your own photos!")
        return

    st.markdown("### 📸 My Photos")

    # Initialize photos list if not exists
    if 'photos' not in favorites[recipe_id]:
        favorites[recipe_id]['photos'] = []

    photos = favorites[recipe_id]['photos']

    # Display existing photos
    if photos:
        for i, photo in enumerate(photos):
            st.markdown(f"**{photo['date']}**")
            try:
                st.image(photo['data'], use_container_width=True)
            except:
                st.warning("Could not load this photo")

            # Show ratings if they exist
            ana_rating = photo.get('ana_rating', 0)
            casey_rating = photo.get('casey_rating', 0)
            if ana_rating > 0 or casey_rating > 0:
                st.markdown(f"**Ana's Rating:** {render_stars(ana_rating)}")
                st.markdown(f"**Casey's Rating:** {render_stars(casey_rating)}")

            # Show photo-specific comment if exists
            photo_comment = photo.get('comment', '')
            if photo_comment:
                st.markdown(f"*{photo_comment}*")

            # Delete button for each photo
            if st.button(f"🗑️ Remove", key=f"del_photo_{recipe_id}_{i}"):
                favorites[recipe_id]['photos'].pop(i)
                save_favorites(favorites)
                st.rerun()

            st.markdown("---")

    # Upload new photo
    st.markdown("**Add a new photo:**")
    uploaded_file = st.file_uploader(
        "Upload photo",
        type=['png', 'jpg', 'jpeg'],
        key=f"photo_upload_{recipe_id}_{len(photos)}",
        label_visibility="collapsed"
    )

    if uploaded_file is not None:
        # Convert to base64 for storage
        import base64
        bytes_data = uploaded_file.getvalue()
        b64_data = base64.b64encode(bytes_data).decode()

        # Preview the photo
        st.image(uploaded_file, caption="Preview", use_container_width=True)

        # Rating inputs
        st.markdown("**Rate this batch:**")
        ana_rating = st.select_slider(
            "Ana's Rating",
            options=[0, 1, 2, 3, 4, 5],
            value=0,
            format_func=lambda x: render_stars(x) if x > 0 else "No rating",
            key=f"ana_rating_{recipe_id}_{len(photos)}"
        )
        casey_rating = st.select_slider(
            "Casey's Rating",
            options=[0, 1, 2, 3, 4, 5],
            value=0,
            format_func=lambda x: render_stars(x) if x > 0 else "No rating",
            key=f"casey_rating_{recipe_id}_{len(photos)}"
        )

        # Comment for this specific photo/batch
        photo_comment = st.text_input(
            "Notes about this batch:",
            placeholder="How did it turn out? Any tweaks?",
            key=f"photo_comment_{recipe_id}_{len(photos)}"
        )

        if st.button("💾 Save Photo", key=f"save_photo_{recipe_id}"):
            # Add photo with date, ratings, and comment
            photo_entry = {
                'data': f"data:image/{uploaded_file.type.split('/')[-1]};base64,{b64_data}",
                'date': datetime.now().strftime('%B %d, %Y at %I:%M %p'),
                'ana_rating': ana_rating,
                'casey_rating': casey_rating,
                'comment': photo_comment
            }
            favorites[recipe_id]['photos'].append(photo_entry)
            save_favorites(favorites)
            st.success("Photo saved!")
            st.rerun()

def render_timers(recipe_id):
    """Render 3 customizable timers that can run simultaneously"""
    import time as time_module

    # Initialize timer states if not exists
    if 'timer_labels' not in st.session_state:
        st.session_state.timer_labels = {}
    if 'timer_values' not in st.session_state:
        st.session_state.timer_values = {}
    if 'timer_running' not in st.session_state:
        st.session_state.timer_running = {}
    if 'timer_end_times' not in st.session_state:
        st.session_state.timer_end_times = {}
    if 'timer_alarm_playing' not in st.session_state:
        st.session_state.timer_alarm_playing = {}

    st.markdown("### ⏱️ Cooking Timers")

    # Check if any timer needs refresh (is running)
    any_running = False
    needs_alarm = []

    for i in range(1, 4):
        timer_key = f"timer{i}_{recipe_id}"

        # Set default label if not exists
        if timer_key not in st.session_state.timer_labels:
            st.session_state.timer_labels[timer_key] = f"Timer {i}"

        current_label = st.session_state.timer_labels[timer_key]

        st.markdown("---")

        # Timer label editor
        col_label, col_edit = st.columns([3, 1])
        with col_label:
            st.markdown(f"**{current_label}**")
        with col_edit:
            if st.button("✏️", key=f"edit_label_{timer_key}", help="Rename timer"):
                st.session_state[f"editing_{timer_key}"] = True

        # Show label edit input if editing
        if st.session_state.get(f"editing_{timer_key}", False):
            new_label = st.text_input(
                "Timer name:",
                value=current_label,
                key=f"new_label_{timer_key}"
            )
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("Save", key=f"save_label_{timer_key}"):
                    st.session_state.timer_labels[timer_key] = new_label
                    st.session_state[f"editing_{timer_key}"] = False
                    st.rerun()
            with col_cancel:
                if st.button("Cancel", key=f"cancel_label_{timer_key}"):
                    st.session_state[f"editing_{timer_key}"] = False
                    st.rerun()

        # Check if alarm is playing for this timer
        if st.session_state.timer_alarm_playing.get(timer_key, False):
            st.error(f"🔔 **{current_label} is done!**")

            if st.button("🔕 Stop Alarm", key=f"stop_alarm_{timer_key}"):
                st.session_state.timer_alarm_playing[timer_key] = False
                st.rerun()
            continue

        # Check if timer is running
        is_running = st.session_state.timer_running.get(timer_key, False)
        end_time = st.session_state.timer_end_times.get(timer_key, 0)

        if is_running and end_time > 0:
            remaining = end_time - time_module.time()
            if remaining <= 0:
                # Timer finished - mark for alarm
                st.session_state.timer_running[timer_key] = False
                st.session_state.timer_alarm_playing[timer_key] = True
                needs_alarm.append(current_label)
            else:
                any_running = True
                hours = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                secs = int(remaining % 60)
                if hours > 0:
                    st.markdown(f"### ⏳ {hours:02d}:{mins:02d}:{secs:02d}")
                else:
                    st.markdown(f"### ⏳ {mins:02d}:{secs:02d}")

                if st.button("⏹️ Stop", key=f"stop_{timer_key}"):
                    st.session_state.timer_running[timer_key] = False
                    st.session_state.timer_end_times[timer_key] = 0
                    st.rerun()
        else:
            # Timer not running - show input (hours and minutes)
            col_hr, col_min = st.columns(2)
            with col_hr:
                hours = st.number_input(
                    "Hours",
                    min_value=0,
                    max_value=23,
                    value=st.session_state.timer_values.get(f"{timer_key}_hr", 0),
                    key=f"hr_{timer_key}"
                )
            with col_min:
                minutes = st.number_input(
                    "Minutes",
                    min_value=0,
                    max_value=59,
                    value=st.session_state.timer_values.get(f"{timer_key}_min", 0),
                    key=f"min_{timer_key}"
                )

            # Save values
            st.session_state.timer_values[f"{timer_key}_hr"] = hours
            st.session_state.timer_values[f"{timer_key}_min"] = minutes

            if st.button(f"▶️ Start", key=f"start_{timer_key}"):
                total_seconds = hours * 3600 + minutes * 60
                if total_seconds > 0:
                    st.session_state.timer_running[timer_key] = True
                    st.session_state.timer_end_times[timer_key] = time_module.time() + total_seconds
                    st.rerun()
                else:
                    st.warning("Set a time first!")

    # Play alarm sound if any timer finished
    if needs_alarm:
        import streamlit.components.v1 as components
        # Use components.html which reliably executes JavaScript
        alarm_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script>
            window.onload = function() {
                try {
                    var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                    var beepCount = 0;
                    function beep() {
                        if (beepCount >= 15) return;
                        beepCount++;
                        var oscillator = audioCtx.createOscillator();
                        var gainNode = audioCtx.createGain();
                        oscillator.connect(gainNode);
                        gainNode.connect(audioCtx.destination);
                        oscillator.frequency.value = 880;
                        oscillator.type = 'square';
                        gainNode.gain.value = 0.3;
                        oscillator.start();
                        setTimeout(function(){ oscillator.stop(); }, 200);
                    }
                    beep();
                    var interval = setInterval(function() {
                        beep();
                        if (beepCount >= 15) clearInterval(interval);
                    }, 400);
                } catch(e) {
                    console.log('Audio error:', e);
                }
            };
            </script>
        </head>
        <body></body>
        </html>
        """
        components.html(alarm_html, height=0)
        st.balloons()
        st.rerun()

    # Auto-refresh if any timer is running (every 1 second)
    if any_running:
        time_module.sleep(1)
        st.rerun()

def display_recipe(recipe, is_favorite_view=False):
    """Display the extracted recipe"""

    recipe_id = get_recipe_id(recipe)
    favorites = load_favorites()
    categories = load_categories()
    is_favorited = recipe_id in favorites

    # Title and favorite button
    col1, col2 = st.columns([4, 1])
    with col1:
        # Show GF badge if marked
        gf_badge = " 🌾" if is_favorited and favorites[recipe_id].get('gluten_free') else ""
        st.markdown(f"## {recipe['title']}{gf_badge}")
    with col2:
        if is_favorited:
            if st.button("⭐", key="unfav", help="Remove from favorites"):
                del favorites[recipe_id]
                save_favorites(favorites)
                st.rerun()
        else:
            if st.button("☆", key="fav", help="Save to favorites"):
                favorites[recipe_id] = {
                    **recipe,
                    'saved_date': datetime.now().isoformat(),
                    'category': recipe.get('category', 'Uncategorized')
                }
                save_favorites(favorites)
                st.success("Saved to favorites!")
                st.rerun()

    # Category selector (only for favorited recipes) - multi-select
    if is_favorited:
        # Support both old single 'category' and new 'categories' list format
        current_categories = favorites[recipe_id].get('categories', [])
        if not current_categories:
            # Migrate from old single category format
            old_cat = favorites[recipe_id].get('category', 'Uncategorized')
            current_categories = [old_cat] if old_cat else ['Uncategorized']

        new_categories = st.multiselect(
            "Categories",
            options=categories,
            default=[c for c in current_categories if c in categories],
            key="category_select"
        )
        # Ensure at least one category is selected
        if not new_categories:
            new_categories = ['Uncategorized']

        if set(new_categories) != set(current_categories):
            favorites[recipe_id]['categories'] = new_categories
            # Remove old single category field if it exists
            if 'category' in favorites[recipe_id]:
                del favorites[recipe_id]['category']
            save_favorites(favorites)
            st.rerun()

        # Gluten Free toggle
        is_gf = favorites[recipe_id].get('gluten_free', False)
        new_gf = st.checkbox("🌾 Gluten Free (GF)", value=is_gf, key="gf_toggle")
        if new_gf != is_gf:
            favorites[recipe_id]['gluten_free'] = new_gf
            save_favorites(favorites)
            st.rerun()

    # Image
    if recipe.get('image'):
        try:
            st.image(recipe['image'], use_container_width=True)
        except:
            pass

    # Time badges
    times_html = ""
    if recipe.get('prep_time'):
        times_html += f'<span class="time-badge">⏱️ Prep: {format_time(recipe["prep_time"])}</span>'
    if recipe.get('cook_time'):
        times_html += f'<span class="time-badge">🍳 Cook: {format_time(recipe["cook_time"])}</span>'
    if recipe.get('total_time'):
        times_html += f'<span class="time-badge">⏰ Total: {format_time(recipe["total_time"])}</span>'
    if recipe.get('servings'):
        times_html += f'<span class="time-badge">🍽️ {recipe["servings"]}</span>'

    if times_html:
        st.markdown(f'<div style="margin: 16px 0;">{times_html}</div>', unsafe_allow_html=True)

    st.divider()

    # View mode toggle
    if 'view_mode' not in st.session_state:
        st.session_state.view_mode = 'scroll'  # Default to scroll view

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📜 Scroll View", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'scroll' else "secondary"):
            st.session_state.view_mode = 'scroll'
            st.rerun()
    with col2:
        if st.button("📑 Tab View", use_container_width=True,
                     type="primary" if st.session_state.view_mode == 'tabs' else "secondary"):
            st.session_state.view_mode = 'tabs'
            st.rerun()

    st.markdown("")  # Spacing

    # Display based on view mode
    if st.session_state.view_mode == 'tabs':
        # Tabbed view - order: Ingredients, Steps, Conversions, Notes, Timers
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["🥗 Ingredients", "📝 Steps", "📐 Convert", "💬 Notes", "⏱️ Timers"])

        with tab1:
            render_ingredients(recipe, recipe_id)

        with tab2:
            render_steps(recipe, recipe_id)

        with tab3:
            render_conversions()

        with tab4:
            render_comments(recipe, recipe_id, favorites, is_favorited)
            st.divider()
            render_photos(recipe, recipe_id, favorites, is_favorited)

        with tab5:
            render_timers(recipe_id)
    else:
        # Scroll view (original layout) - order: Ingredients, Steps, Conversions, Notes, Timers
        st.markdown("### 🥗 Ingredients")
        render_ingredients(recipe, recipe_id)

        st.divider()

        st.markdown("### 📝 Steps")
        render_steps(recipe, recipe_id)

        st.divider()

        render_conversions()

        st.divider()

        st.markdown("### 💬 Baker/Chef Comments")
        render_comments(recipe, recipe_id, favorites, is_favorited)

        st.divider()

        render_photos(recipe, recipe_id, favorites, is_favorited)

        st.divider()

        render_timers(recipe_id)

    # Source link
    st.markdown("---")
    if recipe.get('source_url'):
        st.markdown(f"[View original recipe]({recipe['source_url']})")

def show_favorites():
    """Display the favorites page"""
    st.markdown("## ⭐ My Favorites")

    favorites = load_favorites()
    categories = load_categories()

    if not favorites:
        st.info("No favorites yet! Extract a recipe and click the star to save it.")
        return

    # Category management section
    with st.expander("⚙️ Manage Categories", expanded=False):
        st.markdown("**Add New Category**")
        col1, col2 = st.columns([3, 1])
        with col1:
            new_cat = st.text_input("Category name", key="new_category", label_visibility="collapsed", placeholder="Enter new category name...")
        with col2:
            if st.button("Add", key="add_cat"):
                if new_cat and new_cat not in categories:
                    categories.insert(-1, new_cat)  # Insert before "Uncategorized"
                    save_categories(categories)
                    st.success(f"Added '{new_cat}'!")
                    st.rerun()
                elif new_cat in categories:
                    st.warning("Category already exists")

        st.markdown("**Remove Category**")
        removable_cats = [c for c in categories if c != "Uncategorized"]
        if removable_cats:
            cat_to_remove = st.selectbox("Select category to remove", removable_cats, key="remove_cat_select")
            if st.button("🗑️ Remove Category", key="remove_cat"):
                # Remove this category from all recipes that have it
                for recipe_id, recipe in favorites.items():
                    # Handle new multi-category format
                    recipe_cats = recipe.get('categories', [])
                    if not recipe_cats:
                        # Migrate from old format
                        old_cat = recipe.get('category', 'Uncategorized')
                        recipe_cats = [old_cat] if old_cat else ['Uncategorized']

                    if cat_to_remove in recipe_cats:
                        recipe_cats.remove(cat_to_remove)
                        # Ensure at least one category remains
                        if not recipe_cats:
                            recipe_cats = ['Uncategorized']
                        favorites[recipe_id]['categories'] = recipe_cats
                        if 'category' in favorites[recipe_id]:
                            del favorites[recipe_id]['category']

                save_favorites(favorites)
                categories.remove(cat_to_remove)
                save_categories(categories)
                st.success(f"Removed '{cat_to_remove}'")
                st.rerun()

    # Group recipes by category (recipes appear under each category they belong to)
    recipes_by_category = {}
    for recipe_id, recipe in favorites.items():
        # Support both old 'category' and new 'categories' list format
        recipe_cats = recipe.get('categories', [])
        if not recipe_cats:
            old_cat = recipe.get('category', 'Uncategorized')
            recipe_cats = [old_cat] if old_cat else ['Uncategorized']

        # Add recipe to each category it belongs to
        for cat in recipe_cats:
            if cat not in recipes_by_category:
                recipes_by_category[cat] = []
            recipes_by_category[cat].append((recipe_id, recipe))

    # Display recipes by category
    for category in categories:
        if category in recipes_by_category and recipes_by_category[category]:
            st.markdown(f"### 📁 {category}")

            for recipe_id, recipe in recipes_by_category[category]:
                # Create unique key suffix using category to avoid duplicates
                key_suffix = f"{recipe_id}_{category.replace(' ', '_')}"

                # Add GF label if marked gluten free
                gf_label = " 🌾 GF" if recipe.get('gluten_free') else ""
                with st.expander(f"🍽️ {recipe['title']}{gf_label}", expanded=False):
                    # Rename recipe title
                    current_title = recipe.get('title', 'Recipe')
                    new_title = st.text_input(
                        "Recipe name:",
                        value=current_title,
                        key=f"title_{key_suffix}"
                    )
                    if new_title != current_title and new_title.strip():
                        if st.button("💾 Save Name", key=f"save_title_{key_suffix}"):
                            favorites[recipe_id]['title'] = new_title.strip()
                            save_favorites(favorites)
                            st.success("Name updated!")
                            st.rerun()

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Open Recipe", key=f"open_{key_suffix}"):
                            st.session_state['recipe'] = recipe
                            st.session_state['source_url'] = recipe.get('source_url', '')
                            st.session_state['view'] = 'recipe'
                            save_session()
                            st.rerun()
                    with col2:
                        # Two-step delete confirmation
                        confirm_key = f"confirm_del_{key_suffix}"
                        if st.session_state.get(confirm_key, False):
                            st.warning("Delete from library?")
                            col_yes, col_no = st.columns(2)
                            with col_yes:
                                if st.button("🗑️ Yes", key=f"yes_del_{key_suffix}"):
                                    del favorites[recipe_id]
                                    save_favorites(favorites)
                                    st.session_state[confirm_key] = False
                                    st.rerun()
                            with col_no:
                                if st.button("✖️ No", key=f"no_del_{key_suffix}"):
                                    st.session_state[confirm_key] = False
                                    st.rerun()
                        else:
                            if st.button("🗑️ Remove", key=f"del_{key_suffix}"):
                                st.session_state[confirm_key] = True
                                st.rerun()

                    # Quick category change - multi-select
                    current_cats = recipe.get('categories', [])
                    if not current_cats:
                        old_cat = recipe.get('category', 'Uncategorized')
                        current_cats = [old_cat] if old_cat else ['Uncategorized']

                    new_cats = st.multiselect(
                        "Categories:",
                        options=categories,
                        default=[c for c in current_cats if c in categories],
                        key=f"cat_{key_suffix}"
                    )
                    # Ensure at least one category
                    if not new_cats:
                        new_cats = ['Uncategorized']

                    if set(new_cats) != set(current_cats):
                        favorites[recipe_id]['categories'] = new_cats
                        if 'category' in favorites[recipe_id]:
                            del favorites[recipe_id]['category']
                        save_favorites(favorites)
                        st.rerun()

                    if recipe.get('saved_date'):
                        saved = datetime.fromisoformat(recipe['saved_date'])
                        st.caption(f"Saved on {saved.strftime('%B %d, %Y')}")

    # Export section
    st.markdown("---")
    st.markdown("### 📤 Export Recipe Book")

    if st.button("Download as Markdown", key="export_md"):
        # Generate markdown content
        md_content = generate_markdown_export(favorites, categories)
        st.download_button(
            label="📥 Click to Download",
            data=md_content,
            file_name="Family_Recipe_Book.md",
            mime="text/markdown",
            key="download_md"
        )

def generate_markdown_export(favorites, categories):
    """Generate a beautifully formatted Markdown file of all recipes"""
    lines = []
    lines.append("# Family Recipe Book")
    lines.append("")
    lines.append(f"*Exported on {datetime.now().strftime('%B %d, %Y')}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Group by category (recipes can appear in multiple categories)
    recipes_by_category = {}
    exported_recipes = set()  # Track which recipes we've already exported
    for recipe_id, recipe in favorites.items():
        recipe_cats = recipe.get('categories', [])
        if not recipe_cats:
            old_cat = recipe.get('category', 'Uncategorized')
            recipe_cats = [old_cat] if old_cat else ['Uncategorized']

        # Only add to the first category to avoid duplication in export
        primary_cat = recipe_cats[0] if recipe_cats else 'Uncategorized'
        if primary_cat not in recipes_by_category:
            recipes_by_category[primary_cat] = []
        # Add category list to recipe for export display
        recipe_copy = dict(recipe)
        recipe_copy['_all_categories'] = recipe_cats
        recipes_by_category[primary_cat].append(recipe_copy)

    # Write each category
    for category in categories:
        if category in recipes_by_category and recipes_by_category[category]:
            lines.append(f"## {category}")
            lines.append("")

            for recipe in recipes_by_category[category]:
                lines.append(f"### {recipe.get('title', 'Recipe')}")
                lines.append("")

                # Show all categories if recipe belongs to multiple
                all_cats = recipe.get('_all_categories', [category])
                if len(all_cats) > 1:
                    lines.append(f"*Categories: {', '.join(all_cats)}*")
                    lines.append("")

                # Add image reference if available
                if recipe.get('image'):
                    lines.append(f"![{recipe.get('title', 'Recipe')}]({recipe['image']})")
                    lines.append("")

                # Add personal notes prominently if they exist
                if recipe.get('comments'):
                    lines.append(f"> **My Notes:** {recipe['comments']}")
                    lines.append("")

                # Times
                time_parts = []
                if recipe.get('prep_time'):
                    time_parts.append(f"Prep: {recipe['prep_time']} min")
                if recipe.get('cook_time'):
                    time_parts.append(f"Cook: {recipe['cook_time']} min")
                if recipe.get('total_time'):
                    time_parts.append(f"Total: {recipe['total_time']} min")
                if recipe.get('servings'):
                    servings = recipe['servings']
                    if isinstance(servings, list):
                        servings = servings[0]
                    time_parts.append(f"Servings: {servings}")

                if time_parts:
                    lines.append(f"*{' | '.join(time_parts)}*")
                    lines.append("")

                # Ingredients
                ingredients = clean_ingredients(recipe.get('ingredients', []))
                if ingredients:
                    lines.append("**Ingredients:**")
                    lines.append("")
                    for ing in ingredients:
                        lines.append(f"- {ing}")
                    lines.append("")

                # Instructions (split any embedded steps)
                instructions = split_embedded_steps(recipe.get('instructions', []))
                if instructions:
                    lines.append("**Instructions:**")
                    lines.append("")
                    for i, step in enumerate(instructions, 1):
                        lines.append(f"{i}. {step}")
                    lines.append("")

                # Source
                if recipe.get('source_url'):
                    lines.append(f"*Source: [{recipe['source_url']}]({recipe['source_url']})*")
                    lines.append("")

                lines.append("---")
                lines.append("")

    return "\n".join(lines)

# Restore session from file (persists across browser tab switches)
restore_session()

# Initialize view state
if 'view' not in st.session_state:
    st.session_state['view'] = 'main'

# Save session state on every page load
save_session()

# Navigation
col1, col2 = st.columns(2)
with col1:
    if st.button("➕ Add Recipe", use_container_width=True):
        st.session_state['view'] = 'main'
        save_session()
        st.rerun()
with col2:
    favorites_count = len(load_favorites())
    if st.button(f"⭐ Favorites ({favorites_count})", use_container_width=True):
        st.session_state['view'] = 'favorites'
        save_session()
        st.rerun()

st.markdown("---")

# Main view
if st.session_state['view'] == 'favorites':
    show_favorites()
else:
    # Main extraction view
    st.markdown("# 🍳 MyKitchen")
    st.markdown("Paste any recipe link to add it to your collection")

    # URL input
    url = st.text_input(
        "Recipe URL",
        placeholder="https://www.allrecipes.com/recipe/...",
        label_visibility="collapsed"
    )

    # Extract button
    if st.button("Get Recipe", type="primary"):
        if url:
            with st.spinner("Fetching recipe..."):
                recipe, error = fetch_recipe(url)

                if error:
                    st.error(error)
                elif recipe:
                    st.session_state['recipe'] = recipe
                    st.session_state['source_url'] = url
                    # Clear previous checkboxes
                    st.session_state.ingredient_checks = {}
                    st.session_state.step_checks = {}
                    save_session()
        else:
            st.warning("Please paste a recipe URL first")

    # Display saved recipe
    if 'recipe' in st.session_state:
        display_recipe(st.session_state['recipe'])

        # Clear button
        if st.button("Clear & Start Over"):
            del st.session_state['recipe']
            if 'source_url' in st.session_state:
                del st.session_state['source_url']
            st.session_state.ingredient_checks = {}
            st.session_state.step_checks = {}
            save_session()
            st.rerun()
