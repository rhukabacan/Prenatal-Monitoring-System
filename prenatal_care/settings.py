# Semaphore SMS Configuration
SEMAPHORE_API_KEY = 'your-api-key-here'
SEMAPHORE_SENDER_NAME = 'RHU'

INSTALLED_APPS = [
    # ...
    'django_q',
    # ...
]

# Simple Django Q configuration
Q_CLUSTER = {
    'name': 'prenatal_care',
    'workers': 1,
    'timeout': 60,
    'retry': 120,
    'queue_limit': 50,
    'bulk': 10,
    'orm': 'default'
} 