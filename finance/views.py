from django.shortcuts import render


def home(request):
    # Placeholder landing page. Becomes the dashboard in a later stage.
    return render(request, 'finance/home.html')
