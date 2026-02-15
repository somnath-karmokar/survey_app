// Sticky Header JS Start
window.onscroll = function() {scrollFunction()};
function scrollFunction() {
if
(document.body.scrollTop > 100 || document.documentElement.scrollTop > 100) {
	document.getElementById("sticky-header").classList.add('sticky_menu');
	} else {
	 document.getElementById("sticky-header").classList.remove('sticky_menu'); 
	}
}
//Hover Dropdown
$(document).ready(function () {
    // For desktop devices
    $('.head_nav .dropdown').hover(function () {
        if ($(window).width() > 768) {
            $(this).find('.dropdown-menu').first().stop(true, true).slideDown(150);
        }
    }, function () {
        if ($(window).width() > 768) {
            $(this).find('.dropdown-menu').first().stop(true, true).slideUp(105);
        }
    });

    // For touch devices (such as tablets or mobile)
    $('.head_nav .dropdown').click(function () {
        if ($(window).width() <= 768) {
            $(this).find('.dropdown-menu').first().stop(true, true).slideToggle(150);
        }
    });

    // For sub-dropdowns
    $('.head_nav .dropdown .dropdown-menu').click(function (e) {
        e.stopPropagation(); // Prevent dropdown close on clicking submenu items
    });
});


/*======================================
Slider Swiper
========================================*/

var swiper = new Swiper('.banner-four-slider', {
	direction: 'vertical',
	speed: 800,
	loop: true,
	autoplay: {
		delay: 4000,
	},
	mousewheelControl: true,
	watchSlidesProgress: true,
	mousewheel: {
		releaseOnEdges: false,
	},
	pagination: {
		el: ".swiper-pagination",
		clickable: true,
	},
	breakpoints: {
		// when window width is >= 320px
		320: {
			slidesPerView: 1,
			loop: true,
		},
		540: {
			slidesPerView: 1,
			loop: true,
		},
		768: {
			slidesPerView: 1,
			loop: true,
		},
		992: {
			slidesPerView: 1,
		},
		1200: {
			slidesPerView: 1,
		},
		1400: {
			slidesPerView: 1,
		},
	},

});

//Poll
$('.js-tilt').tilt({
    glare: true,
    maxGlare: .5
})


//Winner Slider
$(".winner_slide").slick({
  autoplay:true,
  autoplaySpeed:5000,
  speed:500,
  slidesToShow:5,
  slidesToScroll:1,
  pauseOnHover:false,
  arrows: true,
  dots:false,
  pauseOnDotsHover:false,
  cssEase:'linear',
  draggable:true,
  prevArrow: '<button class="slick-arrow prev-arrow for-mob"><i class="fa fa-chevron-left"></i></button>',
  nextArrow: '<button class="slick-arrow next-arrow for-mob"><i class="fa fa-chevron-right"></i></button>',
  responsive: [
    {
      breakpoint: 1366,
      settings: {
        slidesToShow: 4,
      },
    },
    {
      breakpoint: 979,
      settings: {
        slidesToShow: 3,
      },
    },
    {
      breakpoint: 767,
      settings: {
        slidesToShow: 2,
      },
    },
  ],
});