from django.http import HttpResponse
from django.urls import include, path


def test_home_view(request):
    return HttpResponse("home")


def test_crash_view(request):
    raise RuntimeError("boom")


urlpatterns = [
    path('', test_home_view, name='home'),
    path('', include(('surveys.urls', 'surveys'), namespace='surveys')),
    path('crash/', test_crash_view, name='test_crash'),
]
