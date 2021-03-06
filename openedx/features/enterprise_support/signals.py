"""
This module contains signals related to enterprise.
"""

from __future__ import absolute_import

import logging
import six

from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from email_marketing.tasks import update_user

from enterprise.models import EnterpriseCourseEnrollment, EnterpriseCustomer, EnterpriseCustomerUser
from integrated_channels.integrated_channel.tasks import transmit_single_learner_data
from openedx.core.djangoapps.signals.signals import COURSE_GRADE_NOW_PASSED
from openedx.features.enterprise_support.api import enterprise_enabled
from openedx.features.enterprise_support.tasks import clear_enterprise_customer_data_consent_share_cache
from openedx.features.enterprise_support.utils import (
    clear_data_consent_share_cache,
    is_enterprise_learner,
)

log = logging.getLogger(__name__)


@receiver(post_save, sender=EnterpriseCustomerUser)
def update_email_marketing_user_with_enterprise_vars(sender, instance, **kwargs):  # pylint: disable=unused-argument, invalid-name
    """
    Update the SailThru user with enterprise-related vars.
    """
    user = User.objects.get(id=instance.user_id)

    # perform update asynchronously
    update_user.delay(
        sailthru_vars={
            'is_enterprise_learner': True,
            'enterprise_name': instance.enterprise_customer.name,
        },
        email=user.email
    )


@receiver(post_save, sender=EnterpriseCourseEnrollment)
def update_dsc_cache_on_course_enrollment(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """
        clears data_sharing_consent_needed cache after Enterprise Course Enrollment
    """
    clear_data_consent_share_cache(
        instance.enterprise_customer_user.user_id,
        instance.course_id
    )


@receiver(pre_save, sender=EnterpriseCustomer)
def update_dsc_cache_on_enterprise_customer_update(sender, instance, **kwargs):
    """
        clears data_sharing_consent_needed cache after enable_data_sharing_consent flag is changed.
    """
    old_instance = sender.objects.filter(pk=instance.uuid).first()
    if old_instance:   # instance already exists, so it's updating.
        new_value = instance.enable_data_sharing_consent
        old_value = old_instance.enable_data_sharing_consent
        if new_value != old_value:
            kwargs = {'enterprise_customer_uuid': six.text_type(instance.uuid)}
            result = clear_enterprise_customer_data_consent_share_cache.apply_async(kwargs=kwargs)
            log.info(u"DSC: Created {task_name}[{task_id}] with arguments {kwargs}".format(
                task_name=clear_enterprise_customer_data_consent_share_cache.name,
                task_id=result.task_id,
                kwargs=kwargs,
            ))


@receiver(COURSE_GRADE_NOW_PASSED, dispatch_uid="new_passing_enterprise_learner")
def handle_enterprise_learner_passing_grade(sender, user, course_id, **kwargs):  # pylint: disable=unused-argument
    """
    Listen for a learner passing a course, transmit data to relevant integrated channel
    """
    if enterprise_enabled() and is_enterprise_learner(user):
        kwargs = {
            'username': six.text_type(user.username),
            'course_run_id': six.text_type(course_id)
        }

        transmit_single_learner_data.apply_async(kwargs=kwargs)
