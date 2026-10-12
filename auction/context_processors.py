def notifications(request):
    if not request.user.is_authenticated:
        return {"unread_notifications": 0, "recent_notifications": []}
    qs = request.user.notifications.all()
    return {
        "unread_notifications": qs.filter(is_read=False).count(),
        "recent_notifications": qs[:5],
    }
