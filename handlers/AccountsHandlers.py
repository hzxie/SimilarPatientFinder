#!/usr/bin/python
# -*- coding: utf-8 -*-
import logging

from datetime import datetime
from datetime import timedelta
from hashlib import md5
from tornado.escape import json_encode as dump_json
from tornadomail.message import EmailFromTemplate
from tornado.web import asynchronous
from re import match as match_regx
from uuid import uuid4

from handlers.BaseHandler import BaseHandler
from mappers.EmailVerificationMapper import EmailVerificationMapper
from mappers.UserMapper import UserMapper
from mappers.UserGroupMapper import UserGroupMapper

class LoginHandler(BaseHandler):
    def initialize(self, db_session):
        self.user_mapper = UserMapper(db_session)

    @asynchronous
    def get(self):
        is_logging_out  = self.get_argument("logout", default=False, strip=False)
        is_logged_in    = self.get_secure_cookie('user')

        if is_logged_in and is_logging_out:
            self.clear_cookie('user')

        if not is_logged_in or is_logging_out:
            self.render('accounts/login.html', is_logged_out=is_logging_out)
        else:
            self.redirect('/')

    @asynchronous
    def post(self):
        username        = self.get_argument("username", default=None, strip=False)
        password        = self.get_argument("password", default=None, strip=False)
        keep_signed_in  = self.get_argument("keepSignedIn", default=False, strip=False)

        result          = self.is_allow_to_access(username, password)
        username        = result['username']
        del result['username']
        if result['isSuccessful']:
            self.set_secure_cookie('user', username)
            logging.info('User [Username=%s] logged in at %s.' % (username, self.get_user_ip_addr()))

        self.finish(dump_json(result))

    def is_allow_to_access(self, username, password):
        is_account_valid    = False
        is_allow_to_access  = True
        if username and password:
            user = self.get_user_using_username_or_email(username, password)

            if user:
                is_account_valid = True
                
                if user.user_group_slug == 'forbidden':
                    is_allow_to_access = False

        return {
            'isSuccessful': is_account_valid and is_allow_to_access,
            'isUsernameEmpty': False if username else True,
            'isPasswordEmpty': False if password else True,
            'isAccountValid': is_account_valid,
            'isAllowToAccess': is_allow_to_access,
            'username': user.username if user else None
        }

    def get_user_using_username_or_email(self, username, password):
        user = None

        if username.find('@') == -1:
            user = self.user_mapper.get_user_using_username(username)
        else:
            user = self.user_mapper.get_user_using_email(username)

        if user and not user.password == password:
            user = None
        return user

class RegisterHandler(BaseHandler):
    def initialize(self, db_session):
        self.user_mapper        = UserMapper(db_session)
        self.user_group_mapper  = UserGroupMapper(db_session)

    @asynchronous
    def get(self):
        is_logged_in = self.get_secure_cookie('user')

        if not is_logged_in:
            self.render('accounts/register.html')
        else:
            self.redirect('/')

    @asynchronous
    def post(self):
        username        = self.get_argument("username", default=None, strip=False)
        password        = self.get_argument("password", default=None, strip=False)
        email           = self.get_argument("email", default=None, strip=False)

        result          = self.create_user(username, password, email)
        if result['isSuccessful']:
            logging.info('New user [Username=%s] was created at %s' % (username, self.get_user_ip_addr()))
        self.finish(dump_json(result))

    def create_user(self, username, password, email):
        user_group      = self.user_group_mapper.get_user_group_using_slug('users')
        user_group_id   = user_group.user_group_id
        result          = {
            'isUsernameEmpty': False if username else True,
            'isUsernameLegal': True if match_regx(r'^[A-Za-z][A-Za-z0-9_]{5,15}$', username) else False,
            'isUsernameExists': self.is_username_exists(username),
            'isPasswordEmpty': False if password else True,
            'isPasswordLegal': len(password) >= 6 and len(password) <= 16,
            'isEmailEmpty': False if email else True,
            'isEmailLegal': True if match_regx(r'^[A-Za-z0-9\._-]+@[A-Za-z0-9_-]+\.[A-Za-z0-9\._-]+$', email) else False,
            'isEmailExists': self.is_email_exists(email)
        }
        result['isSuccessful'] = not result['isUsernameEmpty']  and     result['isUsernameLegal'] and \
                                 not result['isUsernameExists'] and not result['isPasswordEmpty'] and \
                                     result['isPasswordLegal']  and not result['isEmailEmpty']    and \
                                     result['isEmailLegal']     and not result['isEmailExists']
        if result['isSuccessful']:
            rows_affected = self.user_mapper.create_user(username, md5(password).hexdigest(), email, user_group_id)
            if not rows_affected:
                result['isSuccessful'] = False
        return result

    def is_username_exists(self, username):
        return True if self.user_mapper.get_user_using_username(username) else False

    def is_email_exists(self, email):
        return True if self.user_mapper.get_user_using_email(email) else False

class ForgotPasswordHandler(BaseHandler):
    def initialize(self, db_session, mail_sender):
        self.base_url = self.application.settings['base_url']
        self.mail_sender = mail_sender
        self.user_mapper = UserMapper(db_session)
        self.email_verification_mapper = EmailVerificationMapper(db_session)

    @asynchronous
    def get(self):
        is_logged_in    = self.get_secure_cookie('user')

        if not is_logged_in:
            self.render('accounts/forgot-password.html')
        else:
            self.redirect('/')

    @asynchronous
    def post(self):
        username        = self.get_argument("username", default=None, strip=False)
        email           = self.get_argument("email", default=None, strip=False)
        is_user_exists  = False

        if username and email:
            is_user_exists  = self.is_user_exists(username, email)
            token           = str(uuid4())
            expire_time     = str(datetime.now() + timedelta(days=1))
            self.email_verification_mapper.delete_email_verification(email)
            self.email_verification_mapper.create_email_verification(email, token, expire_time)

            mail  = EmailFromTemplate(
                'Password Reset Request',
                'reset-password.html',
                params={
                    'base_url': self.base_url,
                    'username': username,
                    'email': email,
                    'token': token
                },
                from_email='noreply@hit.edu.cn',
                to=[email],
                connection=self.mail_sender
            )
            mail.send()

        self.finish(dump_json({
            'isSuccessful': is_user_exists,
            'isUserExists': is_user_exists
        }))

    def is_user_exists(self, username, email):
        user = self.user_mapper.get_user_using_username(username)

        if user and user.email == email:
            return True
        return False

class ResetPasswordHandler(BaseHandler):
    def initialize(self, db_session):
        self.user_mapper = UserMapper(db_session)
        self.email_verification_mapper = EmailVerificationMapper(db_session)

    @asynchronous
    def get(self):
        is_logged_in    = self.get_secure_cookie('user')
        email           = self.get_argument("email", default=None, strip=False)
        token           = self.get_argument("token", default=None, strip=False)

        if not is_logged_in:
            is_token_valid  = self.is_token_valid(email, token)
            self.render('accounts/reset-password.html', email=email, 
                token=token, is_token_valid=is_token_valid)
        else:
            self.redirect('/')

    @asynchronous
    def post(self):
        email               = self.get_argument("email", default=None, strip=False)
        token               = self.get_argument("token", default=None, strip=False)
        new_password        = self.get_argument("newPassword", default=None, strip=False)
        confirm_password    = self.get_argument("confirmPassword", default=None, strip=False)
        result              = self.reset_password(email, token, new_password, confirm_password)

        if result['isSuccessful']:
            logging.info('User [Email=%s] reset password at %s' % (email, self.get_user_ip_addr()))
        self.finish(dump_json(result))

    def reset_password(self, email, token, new_password, confirm_password):
        result = {
            'isTokenValid': self.is_token_valid(email, token),
            'isPasswordEmpty': False if new_password else True,
            'isPasswordLegal': len(new_password) >= 6 and len(new_password) <= 16,
            'isPasswordMatched': new_password == confirm_password
        }
        result['isSuccessful'] = result['isTokenValid']    and not result['isPasswordEmpty'] and \
                                 result['isPasswordLegal'] and     result['isPasswordMatched']
        if result['isSuccessful']:
            rows_affected = self.user_mapper.update_password_using_email(email, md5(new_password).hexdigest())
            rows_affected = self.email_verification_mapper.delete_email_verification(email)
            if not rows_affected:
                result['isSuccessful'] = False
        return result

    def is_token_valid(self, email, token):
        ticket = self.email_verification_mapper.get_email_and_token_using_email(email)

        if ticket and ticket.token == token and ticket.expire_time >= datetime.now():
            return True
        return False

class ProfileHandler(BaseHandler):
    def initialize(self, db_session):
        self.user_mapper = UserMapper(db_session)

    @asynchronous
    def get(self):
        current_username = self.get_current_user()
        current_user     = self.get_user_using_username(current_username)
        self.render('accounts/profile.html', user=current_user)

    @asynchronous
    def post(self):
        current_username    = self.get_current_user()
        current_user        = self.get_user_using_username(current_username)
        email               = self.get_argument('email', default=None, strip=False)
        old_password        = self.get_argument('oldPassword', default=None, strip=False)
        new_password        = self.get_argument('newPassword', default=None, strip=False)
        confirm_password    = self.get_argument('confirmPassword', default=None, strip=False)
        result              = self.get_profile_change_result(current_user, email, old_password, new_password, confirm_password)

        if result['isSuccessful']:
            user.email   = email 
            if old_password:
                user.password = md5(new_password).hexdigest()
            rows_affected = self.user_mapper.update_user(user)
            logging.info('User [username=%s] updated profile at %s' % (current_username, self.get_user_ip_addr()))
        
        self.write(dump_json(result))
        self.finish()

    def get_profile_change_result(self, user, email, old_password, new_password, confirm_password):
        result = {
            'isEmailEmpty': False if email else True,
            'isEmailLegal': self.is_email_legal(email),
            'isEmailExists': self.is_email_exists(user, email),
            'isOldPasswordEmpty': False if old_password else True,
            'isOldPasswordCorrect': self.is_password_correct(user, old_password),
            'isNewPasswordLegal': len(new_password) >= 6 and len(new_password) <= 16,
            'isPasswordConfirmed': new_password == confirm_password
        }
        result['isSuccessful']  = not result['isEmailEmpty']    and result['isEmailLegal']       and \
                                  not result['isEmailExists']   and (result['isOldPasswordEmpty'] or result['isOldPasswordCorrect']) and\
                                      result['isPasswordLegal'] and result['isPasswordConfirmed']
        return result

    def get_user_using_username(self, username):
        return self.user_mapper.get_user_using_username(username)

    def get_user_using_email(self, email):
        return self.user_mapper.get_user_using_email(email)

    def is_email_legal(self, email):
        return match_regx(r'^[A-Za-z0-9\._-]+@[A-Za-z0-9_-]+\.[A-Za-z0-9\._-]+$', email)

    def is_email_exists(self, current_user, email):
        user = self.get_user_using_email(email)
        return False if (not user or user.username == current_user.username) else True

    def is_password_correct(self, user, password):
        return user.password == password

class ProjectsHandler(BaseHandler):
    def initialize(self, db_session):
        self.user_mapper = UserMapper(db_session)

    @asynchronous
    def get(self):
        current_user     = self.get_current_user()
        self.render('accounts/projects.html') 
