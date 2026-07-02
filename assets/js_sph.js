var _ = {
	href : function (url) {
		document.location.href = url;
	},
	toggle : function (e, flag) {
	    var a = ['none', 'block'];
	        if (!(flag === 0 || flag === 1)) {
	            flag = (+(document.getElementById(e).style.display != a[1]));
	        }
	        document.getElementById(e).style.display = a[flag];
	        return _;
    },
    confirm : function (msg, url) {
		if ( confirm(msg) ) document.location.href = url;
	},
	confirmSubmit : function (msg, self) {
		if (confirm(msg)) {
    		self.type = 'submit';
	    	self.onclick = '';
    		self.click();
    	}
	},
	sizes : function () {
		var w=window,d=document,e=d.documentElement,g=d.getElementsByTagName('body')[0];
		return {
			width: w.innerWidth||e.clientWidth||g.clientWidth,
			height: w.innerHeight||e.clientHeight||g.clientHeight
		}
	},
	getCookie : function (name) {
		var matches = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/([\.$?*|{}\(\)\[\]\\\/\+^])/g, '\\$1') + "=([^;]*)"));
		return matches ? decodeURIComponent(matches[1]) : '';
	},
	setCookie: function(name, value, options) {
		options = options || {};
		var expires = options.expires;
		if (typeof expires == "number" && expires) {
			var d = new Date();
			d.setTime(d.getTime() + expires*1000);
			expires = options.expires = d;
		}
		if (expires && expires.toUTCString) {
		options.expires = expires.toUTCString();
		}
		value = encodeURIComponent(value);
		var updatedCookie = name + "=" + value;
		for (var propName in options) {
			updatedCookie += "; " + propName;
			var propValue = options[propName];   
			if (propValue !== true) {
				updatedCookie += "=" + propValue;
				}
		}
  		document.cookie = updatedCookie;
	}	
}
