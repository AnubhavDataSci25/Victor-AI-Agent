"""
Google Services Package for Victor 2.0.

Provides modular and extensible automation for Google services (Keep, Calendar, Meet,
and future services) using Victor's shared persistent Chrome browser session.
"""

from app.google_services.base import BaseGoogleService, GoogleServiceError
from app.google_services.calendar import GoogleCalendarService, parse_date, parse_time
from app.google_services.keep import GoogleKeepService
from app.google_services.meet import GoogleMeetService, validate_meet_code
from app.google_services.registry import GoogleServiceRegistry, google_services

# Initialize and register core services
_keep_service = GoogleKeepService()
_calendar_service = GoogleCalendarService()
_meet_service = GoogleMeetService()

google_services.register(_keep_service)
google_services.register(_calendar_service)
google_services.register(_meet_service)

__all__ = [
    "BaseGoogleService",
    "GoogleServiceError",
    "GoogleKeepService",
    "GoogleCalendarService",
    "GoogleMeetService",
    "GoogleServiceRegistry",
    "google_services",
    "validate_meet_code",
    "parse_date",
    "parse_time",
]
