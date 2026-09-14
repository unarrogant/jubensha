document.addEventListener('DOMContentLoaded', function(){
    const loginBtn = this.documentElement.querySelector('.btn-login');
    const registerBtn = this.documentElement.querySelector('.btn-register');
    const accountInput = document.querySelector('.forminput[placeholder="账号"]');
    const passwordInput = document.querySelector('.forminput[placeholder="密码"]');
    const container = document.querySelector('.container');
    const savedUsers = JSON.parse(localStorage.getItem('allUsers')||'[]');
    const regPanel = document.querySelector('.register-panel');
    const mask = document.querySelector('.mask');
    const regAccountInput = document.querySelector('.reg-input[placeholder="设置账号（3-12位）"]');
    const regPwdInput = document.querySelector('.reg-input[placeholder="设置密码（6-16位）"]');
    const regPwdConfirmInput = document.querySelector('.reg-input[placeholder="确认密码"]');
    const regConfirmBtn = document.querySelector('.btn-reg-confirm');
    const regCancelBtn = document.querySelector('.btn-reg-cancel');
    loginBtn.addEventListener('click',function(){
    //非空校验
        const account = accountInput.value.trim();//去掉空格
         const password = passwordInput.value.trim();
        if(!account){
            alert('请输入账号');
        return;//终止后续逻辑
        }
        if(!password){
            alert('请输入密码');
            return;
        }
        if(account === '123' && password === '123'){
        setTimeout(function(){
            container.classList.add('success');
            setTimeout(function(){
                window.location.href = "背景故事.html"; // 与原有登录跳转地址一致
            }, 2000);
        }, 1500);
        return; // 终止后续逻辑，避免进入正常用户校验
       }


        setTimeout(function(){
            const matchedUser=savedUsers.find(user => user.account===account&&user.password===password);           
            if(matchedUser){
                container.classList.add('success');
                setTimeout(function(){
                    window.location.href ="111.html";   //此处添加后面网页地址             
                },2000 );
            }
            else{
                alert('该用户未注册！')
                passwordInput.value='';
            }
        },1500)
    });
    registerBtn.addEventListener('click', function(){
        regPanel.style.display = 'block';
        mask.style.display = 'block';
        // 清空上次残留的输入内容
        regAccountInput.value = '';
        regPwdInput.value = '';
        regPwdConfirmInput.value = '';
    });

    // 关闭注册面板
    regCancelBtn.addEventListener('click', function(){
        regPanel.style.display = 'none';
        mask.style.display = 'none';
    });

    // 点击遮罩层关闭注册面板
    mask.addEventListener('click', function(){
        regPanel.style.display = 'none';
        mask.style.display = 'none';
    });

    // 完成注册逻辑（优化校验规则）
    regConfirmBtn.addEventListener('click', function(){
        const regAccount = regAccountInput.value.trim();
        const regPwd = regPwdInput.value.trim();
        const regPwdConfirm = regPwdConfirmInput.value.trim();

        // 1. 非空校验
        if(!regAccount || !regPwd || !regPwdConfirm){
            alert('账号或密码不能为空！');
            return;
        }

        // 2. 账号长度校验（3-12位）
        if(regAccount.length < 3 || regAccount.length > 12){
            alert('账号需为3-12位字符！');
            return;
        }

        // 3. 密码长度校验（6-16位）
        if(regPwd.length < 6 || regPwd.length > 16){
            alert('密码需为6-16位字符！');
            return;
        }

        // 4. 密码一致性校验
        if(regPwd !== regPwdConfirm){
            alert('两次密码输入不一致！');
            return;
        }

        // 5. 账号唯一性校验
        if(savedUsers.some(user => user.account === regAccount)){
            alert('该账号已存在，请更换账号！');
            return;
        }

        // 6. 保存注册信息
        savedUsers.push({account: regAccount, password: regPwd});
        localStorage.setItem('allUsers', JSON.stringify(savedUsers));
        alert('注册成功！即将返回登录');
        
        // 关闭注册面板
        regPanel.style.display = 'none';
        mask.style.display = 'none';
    });


    passwordInput.addEventListener('keydown', function(e){
        if(e.key==='Enter'){
            loginBtn.click();//回车=click
        }

    });
    // 注册面板回车触发注册
    regPwdConfirmInput.addEventListener('keydown', function(e){
        if(e.key==='Enter'){
            regConfirmBtn.click();
        }
    });
});
