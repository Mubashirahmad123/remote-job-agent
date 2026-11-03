from api.auth import create_user
create_user("admin", "admin123", role="admin")
print("Admin user created")