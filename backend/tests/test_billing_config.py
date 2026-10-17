import pytest

from mebot.config import ConfigError, check_billing


def test_billing_off_in_single_mode_even_with_providers(settings):
    s = settings.model_copy(update={"billing_providers": "stripe"})
    assert s.billing_provider_list == [] and not s.billing_enabled
    check_billing(s)


def test_billing_needs_hosted_and_a_provider(hosted_settings):
    assert not hosted_settings.billing_enabled
    s = hosted_settings.model_copy(
        update={
            "billing_providers": "razorpay, Stripe",
            "razorpay_key_id": "rzp_test_x",
            "razorpay_key_secret": "s",
            "razorpay_webhook_secret": "w",
            "stripe_secret_key": "sk_test_x",
            "stripe_webhook_secret": "whsec_x",
        }
    )
    assert s.billing_provider_list == ["razorpay", "stripe"] and s.billing_enabled
    check_billing(s)


def test_missing_provider_secret_is_a_clear_error(hosted_settings):
    s = hosted_settings.model_copy(
        update={"billing_providers": "stripe", "stripe_secret_key": "sk_test_x"}
    )
    with pytest.raises(ConfigError, match="STRIPE_WEBHOOK_SECRET"):
        check_billing(s)
    with pytest.raises(ConfigError, match="unknown provider"):
        check_billing(hosted_settings.model_copy(update={"billing_providers": "paypal"}))
