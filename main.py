#!/usr/bin/env python3
import asyncio
import sys
import os

# Добавляем корень проекта в PYTHONPATH
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

print(f"📁 Project root: {project_root}")
print(f"📁 Python path: {sys.path[:3]}")

try:
    from app.main import main as app_main
    print("✅ Import successful!")
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("\nChecking structure...")
    
    # Проверяем структуру
    app_init = os.path.join(project_root, 'app', '__init__.py')
    if os.path.exists(app_init):
        print("✅ app/__init__.py exists")
    else:
        print("❌ app/__init__.py MISSING! Creating...")
        with open(app_init, 'w') as f:
            f.write('# app package\n')
    
    # Проверяем другие файлы
    files = ['app/models.py', 'app/config.py']
    for f in files:
        path = os.path.join(project_root, f)
        if os.path.exists(path):
            print(f"✅ {f} exists")
        else:
            print(f"❌ {f} MISSING!")
    
    sys.exit(1)

if __name__ == "__main__":
    try:
        print("🚀 Starting bot...")
        asyncio.run(app_main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)