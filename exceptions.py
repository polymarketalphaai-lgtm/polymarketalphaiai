"""
Business-layer exceptions.

These exceptions represent business rule failures and are raised by db.py.
The HTTP layer (app.py) translates them into appropriate HTTP responses.
"""


class BusinessError(Exception):
    """Base class for all business exceptions."""

    def __init__(self, message: str = "Business rule violation."):
        super().__init__(message)


class ProfileIncompleteError(BusinessError):
    def __init__(self, message: str = "Profile is incomplete."):
        super().__init__(message)


class TrialExpiredError(BusinessError):
    def __init__(self, message: str = "Free trial has expired."):
        super().__init__(message)


class WalletNotFoundError(BusinessError):
    def __init__(self, message: str = "Wallet not found."):
        super().__init__(message)


class InsufficientTokensError(BusinessError):
    def __init__(self, message: str = "Insufficient token balance."):
        super().__init__(message)


class MarketNotFoundError(BusinessError):
    def __init__(self, message: str = "Market not found."):
        super().__init__(message)


class MarketClosedError(BusinessError):
    def __init__(self, message: str = "Market is closed."):
        super().__init__(message)


class TelegramLinkError(BusinessError):
    def __init__(self, message: str = "Telegram linking failed."):
        super().__init__(message)
        
class VerificationCodeError(BusinessError):
    def __init__(self, message: str = "Invalid verification code."):
        super().__init__(message)


class VerificationCodeExpiredError(BusinessError):
    def __init__(self, message: str = "Verification code has expired."):
        super().__init__(message)


class VerificationCodeAttemptsExceededError(BusinessError):
    def __init__(self, message: str = "Maximum verification attempts exceeded."):
        super().__init__(message)


class EmailNotFoundError(BusinessError):
    def __init__(self, message: str = "No account found with this email address."):
        super().__init__(message)