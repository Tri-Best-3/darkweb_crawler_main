import os

#---------------------------------------------------------
# Superset Specific Config
#---------------------------------------------------------
ROW_LIMIT = 5000

# SUPERSET_WEBSERVER_PORT = 8088
#---------------------------------------------------------

#---------------------------------------------------------
# Flask App Builder configuration
#---------------------------------------------------------
# Your App secret key
# The SECRET_KEY is used to encrypt session cookies and other sensitive data.
# It should be a long random string.
SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "this-is-not-secure-please-change-it-in-env")

# The SQLAlchemy connection string to your database backend
# This is the metadata database (where Superset stores charts, dashboards, etc.)
SQLALCHEMY_DATABASE_URI = os.getenv(
    "SUPERSET_METADATA_DB_URI", 
    "postgresql://superset:superset@superset-db:5432/superset"
)

#---------------------------------------------------------
# Caching Config (Redis)
#---------------------------------------------------------
# Caching is important for Superset performance
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 86400,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_URL": os.getenv("SUPERSET_REDIS_URL", "redis://superset-cache:6379/1"),
}
FILTER_STATE_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 86400,
    "CACHE_KEY_PREFIX": "superset_filter_",
    "CACHE_REDIS_URL": os.getenv("SUPERSET_REDIS_URL", "redis://superset-cache:6379/1"),
}
EXPLORE_FORM_DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 86400,
    "CACHE_KEY_PREFIX": "superset_explore_form_",
    "CACHE_REDIS_URL": os.getenv("SUPERSET_REDIS_URL", "redis://superset-cache:6379/1"),
}

#---------------------------------------------------------
# Feature Flags
#---------------------------------------------------------
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}

#---------------------------------------------------------
# Extra Config
#---------------------------------------------------------
# Set to True to load example data on initialization (can be controlled via env)
SUPERSET_LOAD_EXAMPLES = os.getenv("SUPERSET_LOAD_EXAMPLES", "yes") == "yes"
