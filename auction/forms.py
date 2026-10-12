from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Auction, Category, Profile, Report


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class AuctionForm(forms.ModelForm):
    class Meta:
        model = Auction
        fields = (
            "title",
            "description",
            "category",
            "image",
            "starting_price",
            "minimum_increment",
            "start_time",
            "end_time",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("start_time", "end_time"):
            self.fields[field].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
        if not self.is_bound and not self.instance.pk:
            now = timezone.localtime(timezone.now()).replace(second=0, microsecond=0)
            self.initial["start_time"] = (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
            self.initial["end_time"] = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and image.size > 8 * 1024 * 1024:
            raise forms.ValidationError("Auction images must be 8 MB or smaller.")
        return image

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_time")
        end = cleaned.get("end_time")
        now = timezone.now()
        if start and end and end <= start:
            raise forms.ValidationError("End time must be later than start time.")
        if end and end <= now:
            raise forms.ValidationError("End time must be in the future.")
        return cleaned


class MaxBidForm(forms.Form):
    max_amount = forms.DecimalField(min_value=0.01, max_digits=14, decimal_places=2)


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(required=False, max_length=150)
    last_name = forms.CharField(required=False, max_length=150)

    class Meta:
        model = Profile
        fields = ("bio", "avatar")
        widgets = {"bio": forms.Textarea(attrs={"rows": 4})}


    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Profile images must be 5 MB or smaller.")
        return avatar


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ("reason", "details")
        widgets = {"details": forms.Textarea(attrs={"rows": 4})}
