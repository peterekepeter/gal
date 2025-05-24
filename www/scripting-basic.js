
var allow_submit = true;

var inputs = document.querySelectorAll('input')
for (var i = 0; i < inputs.length; i++) {
    inputs[i].addEventListener("keydown", lengthCheck)
}


function lengthCheck(){
    allow_submit = true;
    var inputs = document.querySelectorAll('input')
    for (var i = 0; i < inputs.length; i++) {
        var name = inputs[i].getAttribute("name");
        var value = inputs[i].getAttribute("value");
        if (value.length > 10) {
            allow_submit = false;
            document.querySelectorAll("strong")[0].innerHTML = "Input too long!"
        }
    }
    return allow_submit;
}

document.querySelectorAll("form")[0].addEventListener("submit", function(e) {
    lengthCheck();
    if (!allow_submit) e.preventDefault();
});