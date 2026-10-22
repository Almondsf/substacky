from rest_framework.serializers import ModelSerializer
from apps.accounts.models import CustomUser as User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class RegistrationSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'username', 'email', 'password', 'tenant', 'role']
        read_only_fields = ['id', 'role']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        # Self-registered users are always members; admins are created with their tenant.
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            password=validated_data['password'],
            tenant=validated_data.get('tenant'),
            role=User.Role.MEMBER
        )
        return user



class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.EMAIL_FIELD


class UserSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'username', 'email', 'tenant', 'role']
        read_only_fields = ['id', 'tenant', 'role']
