"""Market hours detection for forex markets."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class MarketHours:
    """
    Forex market hours detection.
    
    Forex markets are open 24/5:
    - Opens: Sunday 5:00 PM ET (22:00 UTC)
    - Closes: Friday 5:00 PM ET (22:00 UTC)
    
    Also handles major holidays (Christmas, New Year).
    """
    
    # Market sessions (times in UTC)
    SESSIONS = {
        'sydney': (22, 7),    # 22:00 - 07:00 UTC
        'tokyo': (0, 9),      # 00:00 - 09:00 UTC
        'london': (8, 17),    # 08:00 - 17:00 UTC
        'new_york': (13, 22), # 13:00 - 22:00 UTC
    }
    
    # Major holidays (month, day) when forex markets are closed
    CLOSED_HOLIDAYS = [
        (12, 25),  # Christmas Day
        (1, 1),    # New Year's Day
    ]
    
    def __init__(self, weekend_bypass: bool = False):
        """
        Initialize market hours checker.
        
        Args:
            weekend_bypass: If True, treat weekends as market open (for testing)
        """
        self._weekend_bypass = weekend_bypass
    
    def is_market_open(self, check_time: Optional[datetime] = None) -> bool:
        """
        Check if forex market is currently open.
        
        Args:
            check_time: Time to check (UTC). If None, uses current time.
            
        Returns:
            True if market is open
        """
        if check_time is None:
            check_time = datetime.now(timezone.utc)
        elif check_time.tzinfo is None:
            check_time = check_time.replace(tzinfo=timezone.utc)
        
        # Weekend bypass for testing
        if self._weekend_bypass:
            return True
        
        # Check if it's a major holiday
        if self._is_holiday(check_time):
            return False
        
        # Check weekend closure
        return self._is_weekday_trading_hours(check_time)
    
    def _is_holiday(self, check_time: datetime) -> bool:
        """Check if the date is a major market holiday."""
        for month, day in self.CLOSED_HOLIDAYS:
            if check_time.month == month and check_time.day == day:
                logger.debug(f"Market closed for holiday: {check_time.date()}")
                return True
        return False
    
    def _is_weekday_trading_hours(self, check_time: datetime) -> bool:
        """
        Check if within Monday-Friday trading hours.
        
        Forex opens Sunday 22:00 UTC and closes Friday 22:00 UTC.
        """
        weekday = check_time.weekday()  # 0=Monday, 6=Sunday
        hour = check_time.hour
        
        # Saturday: always closed
        if weekday == 5:
            return False
        
        # Sunday: only open after 22:00 UTC
        if weekday == 6:
            return hour >= 22
        
        # Friday: only open until 22:00 UTC
        if weekday == 4:
            return hour < 22
        
        # Monday-Thursday: always open
        return True
    
    def get_market_status(self, check_time: Optional[datetime] = None) -> dict:
        """
        Get detailed market status.
        
        Args:
            check_time: Time to check (UTC). If None, uses current time.
            
        Returns:
            Dict with market status details
        """
        if check_time is None:
            check_time = datetime.now(timezone.utc)
        elif check_time.tzinfo is None:
            check_time = check_time.replace(tzinfo=timezone.utc)
        
        is_open = self.is_market_open(check_time)
        
        # Determine current session
        current_session = None
        hour_utc = check_time.hour
        
        for session_name, (start, end) in self.SESSIONS.items():
            if start <= end:
                # Session doesn't cross midnight
                if start <= hour_utc < end:
                    current_session = session_name
                    break
            else:
                # Session crosses midnight
                if hour_utc >= start or hour_utc < end:
                    current_session = session_name
                    break
        
        return {
            'is_open': is_open,
            'current_session': current_session,
            'check_time': check_time.isoformat(),
            'weekday': check_time.strftime('%A'),
            'is_holiday': self._is_holiday(check_time),
        }
    
    def get_next_open_time(self, from_time: Optional[datetime] = None) -> datetime:
        """
        Get the next market open time.
        
        Args:
            from_time: Time to check from (UTC). If None, uses current time.
            
        Returns:
            Next market open time (UTC)
        """
        if from_time is None:
            from_time = datetime.now(timezone.utc)
        elif from_time.tzinfo is None:
            from_time = from_time.replace(tzinfo=timezone.utc)
        
        # If market is currently open, return current time
        if self.is_market_open(from_time):
            return from_time
        
        # Find next open time
        check_time = from_time
        max_iterations = 7 * 24  # Check up to 7 days ahead
        
        for _ in range(max_iterations):
            check_time += timedelta(hours=1)
            if self.is_market_open(check_time):
                return check_time
        
        # Fallback: return time 7 days from now
        return from_time + timedelta(days=7)
    
    def get_next_close_time(self, from_time: Optional[datetime] = None) -> datetime:
        """
        Get the next market close time.
        
        Args:
            from_time: Time to check from (UTC). If None, uses current time.
            
        Returns:
            Next market close time (UTC)
        """
        if from_time is None:
            from_time = datetime.now(timezone.utc)
        elif from_time.tzinfo is None:
            from_time = from_time.replace(tzinfo=timezone.utc)
        
        # If market is currently closed, find next open then close
        if not self.is_market_open(from_time):
            from_time = self.get_next_open_time(from_time)
        
        # Find next close time (Friday 22:00 UTC)
        check_time = from_time
        max_iterations = 7 * 24  # Check up to 7 days ahead
        
        for _ in range(max_iterations):
            check_time += timedelta(hours=1)
            if not self.is_market_open(check_time):
                return check_time
        
        # Fallback: return time 7 days from now
        return from_time + timedelta(days=7)
