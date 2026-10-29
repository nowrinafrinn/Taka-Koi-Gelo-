from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def home(request):
    # Public landing page. Logged-in users go straight to their dashboard.
    if request.user.is_authenticated:
        return redirect('finance:dashboard')
    return render(request, 'finance/home.html')


@login_required
def dashboard(request):
    # Placeholder. Real figures arrive in the dashboard stage.
    return render(request, 'finance/dashboard.html')
