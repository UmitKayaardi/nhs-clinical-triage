from app.db.session import engine
from app.db.base import Base
# Make sure your models are imported so SQLAlchemy knows about them
from app.models import mimic_models 

print("Creating tables for SQLite...")
Base.metadata.create_all(bind=engine)
print("Tables created successfully!")