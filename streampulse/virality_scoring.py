import json

import lightgbm as lgb
import pandas as pd

from streampulse.load import PROJECT_ROOT
from streampulse.virality import CATEGORICAL_FEATURES, NUMERIC_FEATURES

# Scoring only: the app and the title optimizer import this module, so it avoids MLflow and scikit-learn,
# which only training (virality_model.py) needs.
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
MODELS_DIR = PROJECT_ROOT / "models"
CLASSIFIER_PATH = MODELS_DIR / "virality_classifier.txt"
REGRESSOR_PATH = MODELS_DIR / "virality_regressor.txt"
CATEGORIES_PATH = MODELS_DIR / "virality_categories.json"


def feature_matrix(rows, categories):
    """Model inputs: numbers as floats and categorical columns as categories fixed to the training ones."""
    matrix = rows[FEATURE_COLUMNS].copy()
    for column in NUMERIC_FEATURES:
        matrix[column] = matrix[column].astype(float)
    for column in CATEGORICAL_FEATURES:
        matrix[column] = pd.Categorical(matrix[column], categories=categories[column])
    return matrix


def load_saved_models():
    """The saved classifier, regressor and training categories."""
    classifier = lgb.Booster(model_file=str(CLASSIFIER_PATH))
    regressor = lgb.Booster(model_file=str(REGRESSOR_PATH))
    categories = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))
    return classifier, regressor, categories
