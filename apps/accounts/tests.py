from datetime import timedelta
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import CustomUser as User, Invite
from apps.tenants.models import Tenant


class RegistrationTests(APITestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name='Acme', slug='acme')

    def test_registered_user_is_always_member(self):
        response = self.client.post(reverse('register'), {
            'username': 'eve',
            'email': 'eve@example.com',
            'password': 'S3cure-pass!',
            'tenant': str(self.tenant.id),
            'role': 'admin',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.get(email='eve@example.com').role, User.Role.MEMBER)


class MeViewTests(APITestCase):

    def test_anonymous_is_rejected(self):
        response = self.client.get(reverse('me'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_current_user(self):
        user = User.objects.create_user(username='bob', email='bob@example.com', password='x')
        self.client.force_authenticate(user)
        response = self.client.get(reverse('me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'bob@example.com')


class TeamTestCase(APITestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name='Acme', slug='acme')
        self.other_tenant = Tenant.objects.create(name='Other', slug='other')
        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.com', password='x', tenant=self.tenant, role=User.Role.ADMIN
        )
        self.member = User.objects.create_user(
            username='member', email='member@acme.com', password='x', tenant=self.tenant
        )


@override_settings(INVITE_ACCEPT_URL='https://app.test/join')
class InviteTests(TeamTestCase):

    def invite(self, email='new@acme.com', role='member'):
        self.client.force_authenticate(self.admin)
        return self.client.post(reverse('invite-list-create'), {'email': email, 'role': role})

    def accept(self, token, **overrides):
        self.client.force_authenticate(None)
        data = {'token': token, 'username': 'newbie', 'password': 'S3cure-pass!'}
        data.update(overrides)
        return self.client.post(reverse('invite-accept'), data)

    def test_admin_invites_and_email_sent(self):
        response = self.invite(role='admin')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('token', response.data)
        invite = Invite.objects.get()
        self.assertEqual(invite.tenant, self.tenant)
        self.assertEqual(invite.invited_by, self.admin)
        self.assertEqual(mail.outbox[0].to, ['new@acme.com'])
        self.assertIn(f'https://app.test/join?token={invite.token}', mail.outbox[0].body)

    def test_member_cannot_invite(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse('invite-list-create'), {'email': 'x@acme.com'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_invite_existing_user(self):
        self.assertEqual(self.invite(email='MEMBER@acme.com').status_code, status.HTTP_400_BAD_REQUEST)

    def test_reinvite_replaces_open_invite(self):
        self.invite()
        first_token = Invite.objects.get().token
        self.invite()
        self.assertEqual(Invite.objects.count(), 1)
        self.assertNotEqual(Invite.objects.get().token, first_token)

    def test_accept_creates_user_with_invited_role(self):
        self.invite(role='admin')
        invite = Invite.objects.get()
        response = self.accept(invite.token)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='new@acme.com')
        self.assertEqual(user.tenant, self.tenant)
        self.assertEqual(user.role, User.Role.ADMIN)
        self.assertTrue(user.check_password('S3cure-pass!'))
        invite.refresh_from_db()
        self.assertIsNotNone(invite.accepted_at)

    def test_token_is_single_use(self):
        self.invite()
        token = Invite.objects.get().token
        self.accept(token)
        response = self.accept(token, username='second')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('token', response.data)

    def test_expired_invite_rejected(self):
        self.invite()
        invite = Invite.objects.get()
        invite.expires_at = timezone.now() - timedelta(minutes=1)
        invite.save()
        self.assertEqual(self.accept(invite.token).status_code, status.HTTP_400_BAD_REQUEST)
        preview = self.client.get(reverse('invite-accept'), {'token': invite.token})
        self.assertEqual(preview.status_code, status.HTTP_404_NOT_FOUND)

    def test_weak_password_rejected(self):
        self.invite()
        response = self.accept(Invite.objects.get().token, password='123')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email='new@acme.com').exists())

    def test_preview(self):
        self.invite()
        response = self.client.get(reverse('invite-accept'), {'token': Invite.objects.get().token})
        self.assertEqual(response.data['tenant'], 'Acme')
        self.assertEqual(response.data['email'], 'new@acme.com')

    def test_revoke(self):
        self.invite()
        invite = Invite.objects.get()
        response = self.client.delete(reverse('invite-revoke', args=[invite.id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.accept(invite.token).status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_revoke_other_tenants_invite(self):
        invite = Invite.objects.create(tenant=self.other_tenant, email='z@other.com')
        self.client.force_authenticate(self.admin)
        response = self.client.delete(reverse('invite-revoke', args=[invite.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MemberTests(TeamTestCase):

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def test_list_is_tenant_scoped(self):
        User.objects.create_user(username='o', email='o@other.com', password='x', tenant=self.other_tenant)
        response = self.client.get(reverse('member-list'))
        self.assertEqual({m['email'] for m in response.data}, {'admin@acme.com', 'member@acme.com'})

    def test_promote_member(self):
        response = self.client.patch(reverse('member-detail', args=[self.member.id]), {'role': 'admin'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, User.Role.ADMIN)

    def test_cannot_change_own_role(self):
        response = self.client.patch(reverse('member-detail', args=[self.admin.id]), {'role': 'member'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_member_detaches(self):
        response = self.client.delete(reverse('member-detail', args=[self.member.id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.member.refresh_from_db()
        self.assertIsNone(self.member.tenant)

    def test_cannot_remove_self(self):
        response = self.client.delete(reverse('member-detail', args=[self.admin.id]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_cannot_manage(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(reverse('member-list')).status_code, status.HTTP_403_FORBIDDEN)
