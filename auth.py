import sys
sys.path.insert(0, ".")
from src.youtube_auth import get_authenticated_service

svc = get_authenticated_service()
print("✅ YouTube bağlantısı başarılı!")
