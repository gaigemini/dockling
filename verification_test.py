import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

try:
    print("Attempting to import app.main...")
    from app.main import app
    print("✅ Successfully imported app.main")
    
    print("Attempting to import ConversionService...")
    from app.services.conversion_service import ConversionService
    print("✅ Successfully imported ConversionService")
    
    print("Attempting to import SsoService...")
    from app.auth.sso_service import sso_service
    print("✅ Successfully imported SsoService")
    
    print("All core modules imported successfully!")
    sys.exit(0)
except Exception as e:
    print(f"❌ Import failed: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
