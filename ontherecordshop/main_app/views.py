from django.shortcuts import render, redirect, get_object_or_404
from .models import Product, Cart, CartItem, Genre, Wishlist, WishlistItem
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy, reverse
from django.views.generic import DeleteView, TemplateView
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.conf import settings
from django.db.models import Q
import os, stripe
from dotenv import load_dotenv
load_dotenv()

def home(request):
    page_name = "On The Record"
    featured_releases = Product.objects.filter(is_featured=True)[:4]
    new_releases = Product.objects.order_by('-release_date')[:4]
    context = {'page_name': page_name, 'featured_releases': featured_releases, 'new_releases': new_releases}
    return render(request, 'home.html', context)

def products_index(request):
    page_name = "Shop All"
    products = Product.objects.all()
    return render(request, 'products/index.html', { 'products': products, 'page_name': page_name })

def product_detail(request, pk):
    product = Product.objects.get(id=pk)

    product_in_wishlist = None
    if request.user.is_authenticated:
        product_in_wishlist = WishlistItem.objects.filter(wishlist__user=request.user, product=product).first()

    return render(request, 'products/detail.html', { 'product': product, 'product_in_wishlist': product_in_wishlist })

def genre_list(request):
    genres = Genre.objects.all().order_by('name')
    return render(request, 'genre/genre_list.html', {'genres': genres})

def products_by_genre(request, genre_id):
    genre = get_object_or_404(Genre, id=genre_id)
    products = Product.objects.filter(genre=genre)
    return render(request, 'genre/products_by_genre.html', {'genre': genre, 'products': products})

def artist_list(request):
    artists = Product.objects.values('artist').distinct().order_by('artist')
    context = {'artists': artists}
    return render(request, 'artist/artist_list.html', context)

def products_by_artist(request, artist_name):
    products = Product.objects.filter(artist=artist_name)
    context = {'products': products, 'artist_name': artist_name}
    return render(request, 'artist/products_by_artist.html', context)

def search_results(request):
    query = request.GET.get('q')
    results = Product.objects.filter(Q(artist__icontains=query) | Q(album__icontains=query))
    context = {'results': results}
    return render(request, 'search/search_results.html', context)

def signup(request):
    page_name = "Create Account"
    error_message = ''
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
        else:
            error_message = 'Invalid credentials - Please try again.'
    form = UserCreationForm()
    context = {'form':form, 'error': error_message, 'page_name': page_name}
    return render(request, 'registration/signup.html', context)


@login_required
def add_to_cart(request, product_id):
    product = Product.objects.get(id=product_id)
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)

        # Update quantity if the item already exists in the cart
        if not created:
            cart_item.quantity += quantity
        else:
            cart_item.quantity = quantity

        cart_item.save()

        messages.success(request, f"{quantity} x {product.album} added to the cart.")

        referring_url = request.META.get('HTTP_REFERER', '/')
        return redirect(referring_url)

    return render(request, 'products/detail.html', {'product': product})

@login_required
def view_cart(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart)

    subtotal = sum(item.product.price * item.quantity for item in cart_items)

    return render(request, 'cart/view_cart.html', {'cart': cart, 'cart_items': cart_items, 'subtotal': subtotal})

def remove_from_cart(request, cart_item_id):
    cart_item = get_object_or_404(CartItem, id=cart_item_id)
    cart_item.delete()
    return redirect('cart')

def update_cart_item(request, cart_item_id):
    cart_item = CartItem.objects.get(id=cart_item_id)

    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))

        # Validate quantity
        if 1 <= quantity <= cart_item.product.stock:
            cart_item.quantity = quantity
            cart_item.save()
            messages.success(request, f"Quantity Updated For - {cart_item.product.album}.")
        else:
            messages.error(request, "Invalid Quantity.")

        return redirect('cart')

    return render(request, 'products/view_cart.html', {'cart_items': CartItem.objects.filter(cart=request.user.cart)})

@login_required
def add_to_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.method == 'POST':
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)
        wishlist_item, created = WishlistItem.objects.get_or_create(wishlist=wishlist, product=product)

        return redirect('detail', pk=product.id)

    return render(request, 'products/detail.html', {'product': product})

def wishlist(request):
    user_wishlist, created = Wishlist.objects.get_or_create(user=request.user)
    wishlist_items = WishlistItem.objects.filter(wishlist=user_wishlist)
    return render(request, 'wishlist/wishlist.html', {'wishlist_items': wishlist_items})

@login_required
def remove_from_wishlist(request, wishlist_item_id):
    wishlist_item = get_object_or_404(WishlistItem, pk=wishlist_item_id, wishlist__user=request.user)
    wishlist_item.delete()
    return redirect('wishlist')

def checkout(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart)
    subtotal = sum(item.product.price * item.quantity for item in cart_items)
    stripe.api_key = settings.STRIPE_SECRET_KEY
    if request.method == 'POST':
        products_to_update = []
        checkout_session = stripe.checkout.Session.create(
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': item.product.album,
                    },
                    'unit_amount': int(item.product.price * 100),
                },
                'quantity': item.quantity,
            } for item in cart_items],
            mode='payment',
            success_url=request.build_absolute_uri(reverse("success")),
            cancel_url=request.build_absolute_uri(reverse("cancel")), 
        )

        for item in cart_items:
            product = item.product
            product.stock -= item.quantity
            products_to_update.append(product)
        
        Product.objects.bulk_update(products_to_update, ['stock'])

        return redirect(checkout_session.url, code=303)

    return render(request, 'cart/view_cart.html', {'cart': cart, 'cart_items': cart_items, 'subtotal': subtotal})


class SuccessView(TemplateView):
    template_name='cart/success.html'

    def get(self, request):

        user_cart, created = Cart.objects.get_or_create(user=request.user)
        user_cart.products.clear()

        return render(request, self.template_name)

class CancelView(TemplateView):
    template_name='cart/cancel.html'